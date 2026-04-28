"""
Gemini-based Reranker implementation for LLM-as-reranker document scoring.

Uses gemini-2.5-flash-lite via Google AI to score query-document relevance
in a single batch API call, replacing the local cross-encoder model.
"""

import logging
import time
from typing import List, Tuple, Annotated

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from config import RERANKER_BATCH_SIZE
from exceptions import RerankerValidationError, RerankerLLMError

logger = logging.getLogger(__name__)


class RerankerScore(BaseModel):
    """Score assigned to a single document by the reranker."""

    index: Annotated[int, Field(ge=0, description="Document index (0-indexed, must be >= 0)")]
    score: Annotated[float, Field(ge=0.0, le=1.0, description="Relevance score [0.0-1.0]")]

    @field_validator("score", mode="after")
    @classmethod
    def validate_score_bounds(cls, score: float) -> float:
        """Ensure score is exactly bounded to [0.0, 1.0]."""
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"Score must be in [0.0, 1.0], got {score}")
        return score


class RerankerScores(BaseModel):
    """Collection of scores from reranking a batch of documents."""

    scores: list[RerankerScore]

    @field_validator("scores", mode="after")
    @classmethod
    def validate_non_empty(cls, scores: list) -> list:
        """Ensure at least one score is returned."""
        if not scores:
            raise ValueError("RerankerScores.scores must contain at least one score")
        return scores

    @field_validator("scores", mode="after")
    @classmethod
    def validate_indices_unique(cls, scores: list) -> list:
        """Ensure all indices are unique (no duplicate document scoring)."""
        indices = [s.index for s in scores]
        if len(indices) != len(set(indices)):
            duplicates = [i for i in indices if indices.count(i) > 1]
            raise ValueError(f"Duplicate document indices in scores: {set(duplicates)}")
        return scores


SCORING_PROMPT_TEMPLATE = """Rate the relevance of each document to the query on a scale of 0.0 to 1.0.
0.0 means completely irrelevant, 1.0 means perfectly relevant.

Query: {query}

Documents:
{documents}

Return JSON: {{"scores": [{{"index": 0, "score": 0.85}}, ...]}}"""


class GeminiReranker:
    """
    LLM-based reranker using Google Gemini for semantic relevance scoring.

    Scores all candidate documents in a single (or batched) API call by
    prompting gemini-2.5-flash-lite to return JSON relevance scores.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash-lite"):
        self.model_name = model_name
        self.device = "cloud"
        self.batch_size = RERANKER_BATCH_SIZE

        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            streaming=False,
            max_output_tokens=2048,
        )
        self.structured_llm = self.llm.with_structured_output(RerankerScores)

        logger.info(f"GeminiReranker loaded: model={model_name}, batch_size={self.batch_size}")

    def warmup(self) -> float:
        """Prime the API connection with a test scoring call."""
        start_time = time.time()

        dummy_query = "What is the purpose of this warmup function?"
        dummy_doc = Document(
            page_content="This is a warmup document with enough content to be realistic. " * 5,
            metadata={"source": "warmup"}
        )
        self.score_documents(dummy_query, [dummy_doc])

        elapsed = time.time() - start_time
        logger.info(f"GeminiReranker warmup complete in {elapsed:.3f}s")
        return elapsed

    def _build_prompt(self, query: str, documents: List[Document]) -> str:
        """Build the scoring prompt with numbered document excerpts."""
        doc_lines = []
        for i, doc in enumerate(documents):
            text = doc.page_content[:500]
            doc_lines.append(f"[{i}] {text}")

        return SCORING_PROMPT_TEMPLATE.format(
            query=query,
            documents="\n".join(doc_lines)
        )

    def score_documents(
        self,
        query: str,
        documents: List[Document],
        batch_size: int = None
    ) -> List[Tuple[Document, float]]:
        """
        Score documents by relevance to query using batch LLM prompting.

        Args:
            query: The search query string
            documents: List of LangChain Document objects to score
            batch_size: Number of documents per API call.
                        If None, uses self.batch_size (from config).

        Returns:
            List of (Document, score) tuples sorted by score descending.
            Scores are in range [0.0, 1.0].

        Raises:
            RerankerLLMError: If LLM API call fails
            RerankerValidationError: If output validation fails
        """
        if not documents:
            return []

        if batch_size is None:
            batch_size = self.batch_size

        all_scored: List[Tuple[Document, float]] = []

        for batch_idx in range(0, len(documents), batch_size):
            batch_docs = documents[batch_idx:batch_idx + batch_size]
            prompt = self._build_prompt(query, batch_docs)

            try:
                result = self.structured_llm.invoke([HumanMessage(content=prompt)])
            except Exception as e:
                logger.error(
                    "reranker_llm_error: %s (batch_size=%d)",
                    type(e).__name__,
                    len(batch_docs),
                    extra={
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "query_length": len(query),
                        "batch_size": len(batch_docs),
                    }
                )
                raise RerankerLLMError(
                    f"LLM scoring failed: {type(e).__name__}",
                    batch_size=len(batch_docs),
                    recoverable=True,
                ) from e

            # Build score map from valid scores only (skip out-of-range indices)
            valid_scores = [s for s in result.scores if 0 <= s.index < len(batch_docs)]
            invalid_indices = [s.index for s in result.scores if not (0 <= s.index < len(batch_docs))]

            if invalid_indices:
                # Check if indices are significantly out of range (clearly erroneous)
                # Allow small overages (e.g., index 1 for batch size 1 due to batching artifacts)
                batch_size = len(batch_docs)
                significantly_invalid = [idx for idx in invalid_indices if idx >= batch_size + 5]

                if significantly_invalid:
                    logger.error(
                        "reranker_invalid_indices: %s",
                        significantly_invalid,
                        extra={
                            "invalid_indices": significantly_invalid,
                            "batch_size": batch_size,
                        }
                    )
                    raise RerankerValidationError(
                        f"LLM returned invalid document indices: {significantly_invalid}",
                        num_docs=batch_size,
                        recoverable=False,
                    )
                else:
                    logger.warning(
                        "reranker_invalid_indices: %s",
                        invalid_indices,
                        extra={
                            "invalid_indices": invalid_indices,
                            "batch_size": batch_size,
                        }
                    )

            score_map = {s.index: s.score for s in valid_scores}

            # Check for missing documents
            missing_indices = [i for i in range(len(batch_docs)) if i not in score_map]
            if missing_indices:
                logger.warning(
                    "reranker_missing_scores: %s",
                    missing_indices,
                    extra={
                        "missing_indices": missing_indices,
                        "batch_size": len(batch_docs),
                    }
                )
                # Use fallback (0.5) only for missing indices, not all documents
                for missing_idx in missing_indices:
                    score_map[missing_idx] = 0.5

            scores = [score_map[i] for i in range(len(batch_docs))]

            for doc, score in zip(batch_docs, scores):
                all_scored.append((doc, score))

        all_scored.sort(key=lambda x: x[1], reverse=True)
        return all_scored

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int
    ) -> List[Tuple[Document, float]]:
        """
        Rerank documents and return top-k most relevant results.

        Args:
            query: The search query string
            documents: List of LangChain Document objects to rerank
            top_k: Maximum number of documents to return

        Returns:
            List of (Document, score) tuples for top-k results sorted by score descending.
        """
        scored_docs = self.score_documents(query, documents)
        return scored_docs[:top_k]
