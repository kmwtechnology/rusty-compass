"""
Configuration constants for Lucille Documentation RAG Agent
"""

import os
from pathlib import Path
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

__all__ = [
    # Google AI configuration
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "EMBEDDINGS_MODEL",
    "GOOGLE_API_KEY",
    # PostgreSQL configuration
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "DATABASE_URL",
    "DB_CONNECTION_KWARGS",
    "DB_POOL_MAX_SIZE",
    # Vector configuration
    "VECTOR_DIMENSION",
    "VECTOR_COLLECTION_NAME",
    # OpenSearch configuration
    "OPENSEARCH_HOST",
    "OPENSEARCH_PORT",
    "OPENSEARCH_USER",
    "OPENSEARCH_PASSWORD",
    "OPENSEARCH_USE_SSL",
    "OPENSEARCH_VERIFY_CERTS",
    "OPENSEARCH_INDEX_NAME",
    "OPENSEARCH_SEARCH_PIPELINE",
    "OPENSEARCH_TIMEOUT",
    # Embedding cache configuration
    "ENABLE_EMBEDDING_CACHE",
    "EMBEDDING_CACHE_MAX_SIZE",
    # Retriever configuration
    "RETRIEVER_K",
    "RETRIEVER_FETCH_K",
    "RETRIEVER_ALPHA",
    "RETRIEVER_SEARCH_TYPE",
    # Reranker configuration
    "ENABLE_RERANKING",
    "RERANKER_MODEL",
    "RERANKER_FETCH_K",
    "RERANKER_TOP_K",
    "RERANKER_BATCH_SIZE",
    "RERANKER_WARMUP_ENABLED",
    # Agent configuration
    "RETRIEVER_TOOL_NAME",
    "RETRIEVER_TOOL_DESCRIPTION",
    "AGENT_MODEL",
    # Query evaluation configuration
    "ENABLE_QUERY_EVALUATION",
    "DEFAULT_ALPHA",
    "QUERY_EVAL_TIMEOUT_MS",
    "ENABLE_QUERY_EVAL_CACHE",
    "QUERY_EVAL_CACHE_MAX_SIZE",
    "QUERY_EVAL_MODEL",
    "QUERY_EVAL_TEMPERATURE",
    "QUERY_EVAL_MAX_TOKENS",
    # Alpha refinement configuration (Phase 3)
    "ENABLE_ALPHA_REFINEMENT",
    "ALPHA_REFINEMENT_THRESHOLD",
    # Iterative retrieval configuration (Phase 4)
    "ENABLE_ITERATIVE_RETRIEVAL",
    "CONFIDENCE_THRESHOLD",
    "MAX_RETRIEVAL_ATTEMPTS",
    "QUERY_REWRITER_MODEL",
    # Link verification configuration
    "ENABLE_LINK_VERIFICATION",
    "LINK_VERIFICATION_TIMEOUT_MS",
    "LINK_CACHE_TTL_MINUTES",
    "MIN_VALID_DOCUMENTS",
    # Project paths
    "BASE_DIR",
    # Lucille documentation source
    "LUCILLE_PROJECT_DIR",
    "LUCILLE_JAVADOC_PATH",
    # Sample data
    "DEFAULT_THREAD_ID",
    # Conversation compaction
    "ENABLE_COMPACTION",
    "MAX_CONTEXT_TOKENS",
    "COMPACTION_THRESHOLD_PCT",
    "MESSAGES_TO_KEEP_FULL",
    "MIN_MESSAGES_FOR_COMPACTION",
    "TOKEN_CHAR_RATIO",
    # Observable agent streaming configuration
    "ENABLE_ASYNC_STREAMING",
    # API Security
    "API_KEY",
    "API_KEY_HEADER",
    "API_KEY_QUERY_PARAM",
    "RATE_LIMIT_CONVERSATIONS",
    "RATE_LIMIT_CHAT",
    "RATE_LIMIT_ENABLED",
    # Server
    "PORT",
    # Logging
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LOG_INCLUDE_TIMESTAMP",
    # LangSmith Observability
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_TRACING_ENABLED",
    # Advanced Streaming
    "ENABLE_ASTREAM_EVENTS",
    # Checkpoint Optimization
    "CHECKPOINT_SELECTIVE_SERIALIZATION",
    "CHECKPOINT_KEEP_VERSIONS",
    "CHECKPOINT_COMPACTION_DAYS",
    # Multi-Capability Agent
    "ENABLE_CONFIG_BUILDER",
    "ENABLE_DOC_WRITER",
    # Content Type Classification
    "ENABLE_CONTENT_TYPE_CLASSIFICATION",
    "CONTENT_TYPE_CLASSIFIER_MODEL",
    "CONTENT_TYPE_CLARIFICATION_THRESHOLD",
]

# ============================================================================
# GOOGLE AI CONFIGURATION
# ============================================================================

# Google API Key (required for Gemini models)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# LLM Model (Gemini)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = int(os.getenv("LLM_TEMPERATURE", 0))

# Embeddings Model (Gemini)
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "models/gemini-embedding-001")

# ============================================================================
# POSTGRES CONFIGURATION
# ============================================================================

# Database connection details (use environment variables for Docker compatibility)
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "langchain_agent")

# Cloud SQL uses Unix sockets at /cloudsql/PROJECT:REGION:INSTANCE
# When detected, skip TCP port and use socket-based connection string
if POSTGRES_HOST.startswith("/cloudsql/"):
    POSTGRES_PORT = None
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@/{POSTGRES_DB}?host={POSTGRES_HOST}"
else:
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Server port (Cloud Run sets PORT env var)
PORT = int(os.getenv("PORT", 8000))

# Connection pool settings
DB_CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,  # Required for PostgresSaver
}
DB_POOL_MAX_SIZE = 20

# ============================================================================
# VECTOR CONFIGURATION
# ============================================================================

# Vector embedding dimension (gemini-embedding-001 with output_dimensionality=768)
# Default is 3072 but 768 is recommended: nearly identical quality (MTEB 67.99 vs 68.16),
# 4x less storage
VECTOR_DIMENSION = 768

# Collection name for vector storage
# Use "lucille_docs" for Lucille API documentation
VECTOR_COLLECTION_NAME = "lucille_docs"

# ============================================================================
# OPENSEARCH CONFIGURATION
# ============================================================================

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "34.138.97.13")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", 9200))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
OPENSEARCH_INDEX_NAME = os.getenv("OPENSEARCH_INDEX_NAME", "rusty_compass_docs")
OPENSEARCH_SEARCH_PIPELINE = os.getenv("OPENSEARCH_SEARCH_PIPELINE", "hybrid_search_pipeline")
OPENSEARCH_TIMEOUT = int(os.getenv("OPENSEARCH_TIMEOUT", 30))

# ============================================================================
# EMBEDDING CACHE CONFIGURATION
# ============================================================================

# Enable query embedding caching (reduces latency for repeated queries)
ENABLE_EMBEDDING_CACHE = os.getenv("ENABLE_EMBEDDING_CACHE", "true").lower() == "true"

# Maximum number of cached query embeddings
EMBEDDING_CACHE_MAX_SIZE = int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", 100))

# ============================================================================
# RETRIEVER CONFIGURATION
# ============================================================================

# Number of documents to retrieve from vector store
RETRIEVER_K = 10

# Number of documents to fetch before filtering (for hybrid search)
# Increased to 40 to provide more diverse candidates for reranking
RETRIEVER_FETCH_K = 40

# Lambda multiplier for hybrid search (standard convention: 0.0 = pure lexical/BM25, 1.0 = pure semantic/vector)
# Optimized from benchmarks: 0.25 provides best quality (0.611) with acceptable latency (22ms)
RETRIEVER_ALPHA = 0.25

# Default search type: "similarity" (vector-only) or "hybrid" (vector + lexical using RRF)
RETRIEVER_SEARCH_TYPE = "hybrid"

# ============================================================================
# RERANKER CONFIGURATION (Gemini LLM-as-Reranker)
# ============================================================================

# Enable reranking of hybrid search results using LLM scoring
ENABLE_RERANKING = True

# Gemini model for LLM-based reranking (scores documents via batch prompting)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "gemini-2.5-flash-lite")

# Number of candidates to fetch before reranking
RERANKER_FETCH_K = 40

# Final number of documents to return after reranking
RERANKER_TOP_K = 10

# Documents per API call (all scored in a single prompt per batch)
RERANKER_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", 20))

# Enable API connection priming on startup to reduce first-query latency
RERANKER_WARMUP_ENABLED = os.getenv("RERANKER_WARMUP_ENABLED", "true").lower() == "true"

# ============================================================================
# QUERY EVALUATOR CONFIGURATION
# ============================================================================

# Enable intelligent query evaluation for dynamic alpha adjustment
ENABLE_QUERY_EVALUATION = True

# Default alpha when evaluation is disabled or fails (0.0 = lexical, 1.0 = semantic)
DEFAULT_ALPHA = 0.25

# Query evaluation timeout (milliseconds) - max time to wait for LLM evaluation
QUERY_EVAL_TIMEOUT_MS = 3000  # 3 seconds max for LLM evaluation

# Query evaluator caching configuration
ENABLE_QUERY_EVAL_CACHE = True
QUERY_EVAL_CACHE_MAX_SIZE = 100

# Query evaluator model settings (lightweight alpha estimator)
QUERY_EVAL_MODEL = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")
QUERY_EVAL_TEMPERATURE = float(os.getenv("QUERY_EVAL_TEMPERATURE", "0"))
QUERY_EVAL_MAX_TOKENS = int(os.getenv("QUERY_EVAL_MAX_TOKENS", "1024"))

# ============================================================================
# ALPHA REFINEMENT CONFIGURATION (Phase 3)
# ============================================================================

# Enable automatic alpha refinement when initial results have low relevance
# Single retry with adjusted alpha if top reranker score < threshold
ENABLE_ALPHA_REFINEMENT = os.getenv("ENABLE_ALPHA_REFINEMENT", "true").lower() == "true"

# Retry if top reranker score is below this threshold (0.0-1.0)
# Default: 0.5 (moderate threshold)
ALPHA_REFINEMENT_THRESHOLD = float(os.getenv("ALPHA_REFINEMENT_THRESHOLD", "0.5"))

# ============================================================================
# ITERATIVE RETRIEVAL CONFIGURATION (Phase 4)
# ============================================================================

# Enable confidence-based retrieval loops (OPT-IN - disabled by default)
# When enabled, checks if top reranker score < CONFIDENCE_THRESHOLD
# If low confidence, rewrites query and retries (max MAX_RETRIEVAL_ATTEMPTS times)
ENABLE_ITERATIVE_RETRIEVAL = os.getenv("ENABLE_ITERATIVE_RETRIEVAL", "false").lower() == "true"

# Retry if top reranker score is below this threshold (0.0-1.0)
# Default: 0.6 (moderate confidence threshold)
# Only used if ENABLE_ITERATIVE_RETRIEVAL is true
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))

# Maximum total retrieval attempts (includes initial attempt)
# Default: 3 (initial + 2 retries)
# Only used if ENABLE_ITERATIVE_RETRIEVAL is true
MAX_RETRIEVAL_ATTEMPTS = int(os.getenv("MAX_RETRIEVAL_ATTEMPTS", "3"))

# Model for query rewriting (lightweight)
# Default: gemini-2.5-flash-lite (same as query evaluator)
QUERY_REWRITER_MODEL = os.getenv("QUERY_REWRITER_MODEL", "gemini-2.5-flash-lite")

# ============================================================================
# LINK VERIFICATION CONFIGURATION
# ============================================================================

# Enable verification of citation links before sending to LLM
# When enabled, checks if all document URLs are accessible (not 404)
# Replaces broken-link documents with valid alternatives to maintain document count
ENABLE_LINK_VERIFICATION = os.getenv("ENABLE_LINK_VERIFICATION", "true").lower() == "true"

# Timeout per URL check in milliseconds
# URLs that don't respond within this time are marked as broken
# Default: 2000ms (2 seconds)
LINK_VERIFICATION_TIMEOUT_MS = int(os.getenv("LINK_VERIFICATION_TIMEOUT_MS", "2000"))

# Cache TTL for verification results in minutes
# Avoids re-checking the same URL repeatedly
# Default: 60 minutes
LINK_CACHE_TTL_MINUTES = int(os.getenv("LINK_CACHE_TTL_MINUTES", "60"))

# Minimum number of documents to maintain after link verification
# If documents are removed due to broken links, replacements are found
# to maintain this count
# Default: 10 (standard retrieval count)
MIN_VALID_DOCUMENTS = int(os.getenv("MIN_VALID_DOCUMENTS", "10"))

# ============================================================================
# AGENT CONFIGURATION
# ============================================================================

# DEPRECATED: These were used for ReAct agent tool binding, now replaced by
# direct retrieval pipeline. Kept for backward compatibility.
# TODO: Remove in next major version
RETRIEVER_TOOL_NAME = "knowledge_base"
RETRIEVER_TOOL_DESCRIPTION = "Search for information in the local document index."
AGENT_MODEL = LLM_MODEL  # DEPRECATED: Use LLM_MODEL directly

# ============================================================================
# PROJECT PATHS
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# LUCILLE DOCUMENTATION SOURCE
# ============================================================================

# Path to Lucille project directory
LUCILLE_PROJECT_DIR = os.getenv(
    "LUCILLE_PROJECT_DIR",
    str(Path(BASE_DIR).parent / "lucille")
)

# Path to Lucille javadoc API documentation
LUCILLE_JAVADOC_PATH = Path(LUCILLE_PROJECT_DIR) / "target" / "site" / "apidocs"

# ============================================================================
# SAMPLE DATA
# ============================================================================

# Default conversation thread ID (can be overridden per conversation)
DEFAULT_THREAD_ID = "default_thread"

# ============================================================================
# CONVERSATION COMPACTION (Smart Context Management)
# ============================================================================

# Enable automatic conversation compaction
ENABLE_COMPACTION = True

# Maximum estimated tokens in context (conservative estimate for gemini-2.5-flash)
MAX_CONTEXT_TOKENS = 3000

# Trigger compaction at this percentage of max context (0.8 = 80%)
COMPACTION_THRESHOLD_PCT = 0.8

# Keep this many recent messages uncompacted (always preserved in full)
MESSAGES_TO_KEEP_FULL = 10

# Minimum number of messages before considering compaction
MIN_MESSAGES_FOR_COMPACTION = 20

# Token estimation (1 token ≈ 4 characters, conservative)
TOKEN_CHAR_RATIO = 4

# ============================================================================
# OBSERVABLE AGENT STREAMING CONFIGURATION
# ============================================================================

# Enable incremental async streaming for improved responsiveness (EXPERIMENTAL)
# When False (default): Backward compatible behavior - waits for entire node completion
#   - Runs entire graph in executor, collects all timing info after completion
#   - More blocking but stable behavior
# When True: Improved streaming with incremental event emission
#   - Emits NodeStartEvent immediately when node begins execution
#   - Processes events as they complete instead of waiting for full node
#   - Emits NodeEndEvent with accurate timing after processing
#   - TRADEOFF: Timing may be slightly less accurate than legacy mode, but
#     provides better UI responsiveness and prevents async event loop blocking
ENABLE_ASYNC_STREAMING = True

# ============================================================================
# API SECURITY CONFIGURATION
# ============================================================================

# API Key authentication (REQUIRED)
# Set API_KEY environment variable to enable authentication
# The API will fail to start if API_KEY is not set
API_KEY = os.getenv("API_KEY")
API_KEY_HEADER = "X-API-Key"
API_KEY_QUERY_PARAM = "api_key"  # For WebSocket authentication

# Rate limiting configuration
RATE_LIMIT_CONVERSATIONS = "10/minute"  # List/manage conversations
RATE_LIMIT_CHAT = "20/minute"           # Chat requests (REST + WebSocket)
RATE_LIMIT_ENABLED = True

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")  # "json" for production, "console" for development
LOG_INCLUDE_TIMESTAMP = True

# ============================================================================
# LANGSMITH OBSERVABILITY CONFIGURATION
# ============================================================================

# LangSmith tracing (optional - requires API key from https://smith.langchain.com)
# Enable by setting LANGSMITH_API_KEY environment variable
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "rusty-compass")
LANGSMITH_TRACING_ENABLED = LANGSMITH_API_KEY is not None

# ============================================================================
# ADVANCED STREAMING CONFIGURATION
# ============================================================================

# Enable astream_events for fine-grained token-level streaming (EXPERIMENTAL)
# When True: Uses LangGraph's astream_events v2 API for token-by-token streaming
# When False: Uses existing streaming mode (entire node outputs)
# Requires LangGraph >= 1.0.5
ENABLE_ASTREAM_EVENTS = os.getenv("ENABLE_ASTREAM_EVENTS", "false").lower() == "true"

# ============================================================================
# CHECKPOINT OPTIMIZATION CONFIGURATION
# ============================================================================

# Enable selective state serialization (excludes large fields from checkpoints)
# Reduces checkpoint size by ~10x by excluding retrieved_documents and document_grades
# These fields are regenerated on retrieval, not needed for conversation continuity
CHECKPOINT_SELECTIVE_SERIALIZATION = True

# Number of recent checkpoint versions to keep per thread during compaction
CHECKPOINT_KEEP_VERSIONS = 3

# Compact checkpoints older than this many days
CHECKPOINT_COMPACTION_DAYS = 7

# ============================================================================
# MULTI-CAPABILITY AGENT CONFIGURATION
# ============================================================================

# Enable Config Builder mode (generates Lucille HOCON pipeline configs)
ENABLE_CONFIG_BUILDER = os.getenv("ENABLE_CONFIG_BUILDER", "true").lower() == "true"

# Enable Documentation Writer mode (generates multi-section documentation)
ENABLE_DOC_WRITER = os.getenv("ENABLE_DOC_WRITER", "true").lower() == "true"

# Enable Content Type Classification (sub-routing within doc_writer)
# When enabled, documentation_request intent routes to classifier first
# When disabled, documentation_request routes directly to doc_planner
ENABLE_CONTENT_TYPE_CLASSIFICATION = os.getenv("ENABLE_CONTENT_TYPE_CLASSIFICATION", "true").lower() == "true"

# Content type classifier model (reuses lightweight query evaluator model)
CONTENT_TYPE_CLASSIFIER_MODEL = os.getenv("CONTENT_TYPE_CLASSIFIER_MODEL", QUERY_EVAL_MODEL)

# Confidence threshold for content type clarification
# When classifier confidence < threshold, ask user to clarify
# Default: 0.90 (90%) - balances accuracy vs interruption
CONTENT_TYPE_CLARIFICATION_THRESHOLD = float(os.getenv("CONTENT_TYPE_CLARIFICATION_THRESHOLD", "0.90"))
