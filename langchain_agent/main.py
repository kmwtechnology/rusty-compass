#!/usr/bin/env python3
"""
Lucille Documentation RAG Agent with Real-Time Streaming, Local Knowledge Base, and Persistent Memory

A production-grade ReAct agent with the following features:
- Real-time character-by-character streaming of agent thinking and final responses
- Hybrid vector/lexical search using OpenSearch with semantic embeddings
- Intelligent document reranking using LLM-as-reranker (Gemini)
- Persistent conversation memory using PostgreSQL with LangGraph checkpointer
- Intelligent tool usage for knowledge retrieval
- Multi-turn conversations with context preservation
- Real-time observability with typed WebSocket events

Powered by:
- LLM: Google Gemini (gemini-2.5-flash) for reasoning and reranking
- Embeddings: Google Gemini (gemini-embedding-001) for semantic search
- Vector Store: OpenSearch 2.19.1 with native hybrid search (vector + text)
- Database: PostgreSQL for conversation checkpoints and metadata
- Memory: LangGraph with PostgreSQL checkpointer
- Framework: LangGraph with ReAct agent pattern
- Observability: Pydantic-validated WebSocket events with real-time streaming
"""

import sys
import uuid
import warnings
import time
import json
import logging
import httpx
import psycopg
from typing import Sequence, Tuple, List, Optional, Dict, Any, Union

# Setup logging
logger = logging.getLogger(__name__)

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph, END
from psycopg_pool import ConnectionPool, AsyncConnectionPool
from langchain_core.messages import SystemMessage, BaseMessage, AIMessage, HumanMessage, ToolMessage
from langchain_core.documents import Document

# Import extracted modules
from agent_state import CustomAgentState
from reranker import GeminiReranker
from vector_store import OpenSearchVectorStore, OpenSearchRetriever
from link_verifier import LinkVerifier
from doc_replacer import DocumentReplacer

# Import event types for observability
try:
    from api.schemas.events import (
        HybridSearchResultEvent, RerankerStartEvent, SearchCandidate,
        SearchProgressEvent, RerankerProgressEvent,
        LinkVerificationEvent, DocumentReplacementEvent,
        LLMResponseStartEvent, LLMResponseChunkEvent,
        QueryExpansionEvent
    )
    _EVENTS_AVAILABLE = True
except ImportError:
    # Event types might not be available in all contexts (e.g., CLI mode)
    HybridSearchResultEvent = None
    RerankerStartEvent = None
    SearchCandidate = None
    SearchProgressEvent = None
    RerankerProgressEvent = None
    LinkVerificationEvent = None
    DocumentReplacementEvent = None
    LLMResponseStartEvent = None
    LLMResponseChunkEvent = None
    QueryExpansionEvent = None
    _EVENTS_AVAILABLE = False

# ============================================================================
# LANGSMITH TRACING (Optional - enable with LANGSMITH_API_KEY env var)
# ============================================================================
import os
if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "rusty-compass")

from pydantic import BaseModel


class AlphaEstimation(BaseModel):
    alpha: float
    reasoning: str


class IntentClassification(BaseModel):
    intent: str
    reasoning: str
    confidence: float
    clarifying_questions: list[str] = []


from config import (
    LLM_MODEL,
    LLM_TEMPERATURE,
    EMBEDDINGS_MODEL,
    VECTOR_DIMENSION,
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    VECTOR_COLLECTION_NAME,
    RETRIEVER_K,
    RETRIEVER_FETCH_K,
    RETRIEVER_ALPHA,
    RETRIEVER_SEARCH_TYPE,
    ENABLE_QUERY_EVALUATION,
    DEFAULT_ALPHA,
    QUERY_EVAL_TIMEOUT_MS,
    GOOGLE_API_KEY,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_DB,
    ENABLE_RERANKING,
    RERANKER_MODEL,
    RERANKER_FETCH_K,
    RERANKER_TOP_K,
    RERANKER_WARMUP_ENABLED,
    ENABLE_COMPACTION,
    MAX_CONTEXT_TOKENS,
    COMPACTION_THRESHOLD_PCT,
    MESSAGES_TO_KEEP_FULL,
    MIN_MESSAGES_FOR_COMPACTION,
    TOKEN_CHAR_RATIO,
    QUERY_EVAL_MODEL,
    QUERY_EVAL_TEMPERATURE,
    QUERY_EVAL_MAX_TOKENS,
)


class LucilleAgent:
    """
    Main agent class that manages the LLM, tools, and conversation state.

    Handles:
    - Real-time streaming of agent thinking and responses
    - Integration with local knowledge base (PostgreSQL + PGVector)
    - Persistent conversation memory (PostgreSQL)
    - Interactive multi-turn conversations
    """

    def __init__(self):
        """Initialize the agent and all its components"""
        self.llm = None
        self.embeddings = None
        self.vector_store = None
        self.pool = None
        self.async_pool = None
        self.checkpointer = None
        self.app = None
        self.thread_id = None
        self.emit_callback = None  # For emitting intermediate events from retriever_node
        self.event_loop = None  # The running event loop (set when emit_callback is set)
        self.event_queue = []  # Queue for intermediate events
        self.retriever = None  # Base retriever
        self.reranker = None  # Cross-encoder reranker
        self.alpha_estimator_llm = None  # Lightweight model for query evaluation

        # Link verification and document replacement
        from config import LINK_VERIFICATION_TIMEOUT_MS, LINK_CACHE_TTL_MINUTES
        self.link_verifier = LinkVerifier(
            timeout_ms=LINK_VERIFICATION_TIMEOUT_MS,
            cache_ttl_minutes=LINK_CACHE_TTL_MINUTES
        )
        self.doc_replacer = DocumentReplacer()

    def verify_prerequisites(self):
        """Verify that all required services are running"""
        print("Verifying prerequisites...")
        print()

        # Check Postgres connection
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    print("✓ Postgres is accessible")
        except Exception as e:
            print(f"✗ Cannot connect to Postgres: {e}")
            print(f"  Connection string: {DATABASE_URL}")
            sys.exit(1)

        # Check OpenSearch connection
        try:
            info = self.vector_store.client.info()
            print(f"✓ OpenSearch is accessible (v{info['version']['number']})")
        except Exception as e:
            print(f"✗ Cannot connect to OpenSearch: {e}")
            sys.exit(1)

        # Check if OpenSearch index has data
        try:
            from config import OPENSEARCH_INDEX_NAME
            count = self.vector_store.client.count(
                index=OPENSEARCH_INDEX_NAME,
                body={"query": {"term": {"collection_id": VECTOR_COLLECTION_NAME}}}
            )["count"]
            if count == 0:
                print(f"✗ No documents found in OpenSearch index")
                print("  Run: python ingest_lucille_docs.py")
                sys.exit(1)
            print(f"✓ OpenSearch has {count} document chunks")
        except Exception as e:
            print(f"✗ Error checking OpenSearch: {e}")
            print("  Run: python setup.py")
            sys.exit(1)

        # Check Google API key
        if not GOOGLE_API_KEY:
            print("✗ GOOGLE_API_KEY not set")
            print("  Set GOOGLE_API_KEY in your .env file or environment")
            sys.exit(1)
        print("✓ Google API key configured")

        print()

    def initialize_components(self):
        """Initialize all LLM and storage components"""
        print("Initializing components...")
        print()

        # Initialize LLM with streaming enabled
        print(f"Loading LLM: {LLM_MODEL}")
        self.llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            streaming=True,
            max_output_tokens=8192,
        )
        print("✓ LLM initialized")

        if ENABLE_QUERY_EVALUATION:
            print(f"Loading query evaluator (alpha estimator): {QUERY_EVAL_MODEL}")
            self.alpha_estimator_llm = ChatGoogleGenerativeAI(
                model=QUERY_EVAL_MODEL,
                temperature=QUERY_EVAL_TEMPERATURE,
                streaming=False,
                max_output_tokens=QUERY_EVAL_MAX_TOKENS,
            )
            self.alpha_structured = self.alpha_estimator_llm.with_structured_output(AlphaEstimation)
            self.intent_structured = self.alpha_estimator_llm.with_structured_output(IntentClassification)
            print("✓ Query evaluator model initialized")
        else:
            self.alpha_estimator_llm = None
            self.alpha_structured = None
            self.intent_structured = None

        # Initialize Embeddings
        print(f"Loading embeddings: {EMBEDDINGS_MODEL}")
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL,
            output_dimensionality=VECTOR_DIMENSION,
        )
        print("✓ Embeddings initialized")

        # Initialize Postgres connection pools (must be before vector store)
        print("Connecting to Postgres checkpoint store...")
        connection_kwargs = DB_CONNECTION_KWARGS.copy()

        # Sync pool for vector store operations
        self.pool = ConnectionPool(
            conninfo=DATABASE_URL,
            max_size=DB_POOL_MAX_SIZE,
            kwargs=connection_kwargs
        )

        # Async pool for checkpointer (required for astream_events)
        self.async_pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            max_size=DB_POOL_MAX_SIZE,
            kwargs=connection_kwargs,
            open=False  # Will be opened asynchronously
        )
        print("✓ Postgres connection pools initialized")

        # Initialize Vector Store using OpenSearch
        print(f"Loading OpenSearch vector store: {VECTOR_COLLECTION_NAME}")
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        print("✓ Vector store initialized")

        # Create base retriever
        self.retriever = self.vector_store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": RERANKER_FETCH_K if ENABLE_RERANKING else RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": RETRIEVER_ALPHA,
            }
        )

        # Initialize Gemini LLM Reranker
        if ENABLE_RERANKING:
            print(f"Loading Gemini reranker: {RERANKER_MODEL}")
            self.reranker = GeminiReranker(model_name=RERANKER_MODEL)
            print("✓ Reranker initialized")

            # Warmup the reranker to prime API connection
            if RERANKER_WARMUP_ENABLED:
                print("Warming up reranker (priming API connection)...")
                warmup_time = self.reranker.warmup()
                print(f"✓ Reranker warmup complete ({warmup_time:.3f}s)")
        else:
            self.reranker = None

        # Checkpointer will be created asynchronously via create_async_checkpointer()
        # This is required because AsyncPostgresSaver needs a running event loop
        self.checkpointer = None
        print("✓ Postgres checkpoint store will be initialized on first use (async)")

        # Ensure conversation metadata table exists
        self._ensure_metadata_table()

        print()

    # ========================================================================
    # AGENT GRAPH NODES FOR DYNAMIC QUERY EVALUATION
    # ========================================================================

    def intent_classifier_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Classify the latest user message to determine intent.

        Intents: question, config_request, documentation_request, summary, follow_up, clarify
        - config_request and documentation_request only included if features are enabled
        - If confidence is low, returns "clarify" intent with questions for the user
        - question is the DEFAULT intent (includes action requests like "Write a tutorial")
        """
        messages = state["messages"]
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, "content") and msg.content:
                user_query = str(msg.content)
                break

        intent, reasoning, confidence, clarifying_questions = self._classify_intent(user_query, messages)
        logger.info(f"Intent classification: intent={intent}, confidence={confidence:.2f}, query={user_query[:50] if user_query else '<empty>'}...")

        # Detect mode shift for workflow state management
        shift_type = self._detect_mode_shift(state, intent)
        current_mode = state.get("agent_mode") or "rag"

        # Prepare extra fields for state cleanup on hard_shift
        extra_fields = {}
        if shift_type == "hard_shift":
            logger.info(
                f"Hard shift detected: {current_mode} → {intent} "
                f"(shift_type={shift_type}). Clearing stale mode-specific state."
            )
            extra_fields = {
                "awaiting_clarification": False,
                "clarification_type": None,
                "clarification_candidates": None,
                "needs_clarification": False,
                "config_components": None,
                "config_output": None,
                "config_validation_notes": None,
                "config_validation_attempts": 0,
                "config_validation_errors": None,
                "config_validation_passed": None,
                "doc_outline": None,
                "doc_gathered_content": None,
                "doc_sections_gathered": None,
                "doc_sections_total": None,
                "retrieved_documents": [],
                "alpha_adjusted": False,
                "_needs_retrieval_retry": False,
                "query_transformed": None,
            }

        return {
            "intent": intent,
            "user_query": user_query,
            "reasoning": reasoning,
            "confidence": confidence,  # For UI display
            "intent_confidence": confidence,
            "clarifying_questions": clarifying_questions,
            "previous_agent_mode": current_mode,
            "mode_shift_type": shift_type,
            **extra_fields,
        }

    def query_evaluator_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Evaluate the query type and determine optimal alpha for hybrid search.

        Lambda interpretation (0.0=lexical, 1.0=semantic):
        - 0.0-0.2: Pure lexical (dates, model numbers, part numbers, exact identifiers)
        - 0.2-0.4: Lexical-heavy (specific versions, brands, frameworks)
        - 0.4-0.6: Balanced (mixed queries with concepts and specific terms)
        - 0.6-0.8: Semantic-heavy (framework guides, optimization techniques)
        - 0.8-1.0: Pure semantic (conceptual questions, "what is", "explain")
        """
        start_time = time.time()
        messages = state["messages"]

        # Extract last user message
        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg.content
                break

        if not last_user_msg:
            # No user message, use optimized default (0.25 = lexical-heavy from benchmarks)
            return {
                "alpha": 0.25,
                "query_analysis": "No query detected",
            }

        print(f"\n[Query Evaluator] Starting evaluation for query: '{last_user_msg[:80]}...'")

        # LLM-based query evaluation - determine optimal alpha for hybrid search
        # Alpha controls lexical/semantic balance; query is used as-is
        evaluation_prompt = f"""Determine the optimal alpha for hybrid search on this query.

=== YOUR TASK ===
Query to analyze: "{last_user_msg}"

=== ALPHA GUIDE (0.0=pure lexical/BM25, 1.0=pure semantic/vector) ===
- 0.00-0.15: PURE LEXICAL - Version numbers, identifiers, class names, exact terms
- 0.15-0.40: LEXICAL-HEAVY - Specific features, APIs, technical terms
- 0.40-0.60: BALANCED - Feature tutorials, patterns, how-to guides
- 0.60-0.75: SEMANTIC-HEAVY - Architectural concepts, optimization strategies
- 0.75-1.0: PURE SEMANTIC - Conceptual "What is" questions, general explanations

=== EXAMPLES ===
"LangChain 0.3.0 release notes" → alpha=0.05 (version number needs exact match)
"LANGCHAIN_API_KEY env var" → alpha=0.08 (exact identifier)
"BaseChatModel class" → alpha=0.10 (class name - lexical)
"checkpointer setup" → alpha=0.25 (specific feature)
"state management patterns" → alpha=0.45 (patterns - balanced)
"How to build multi-agent systems" → alpha=0.55 (how-to - semantic helps)
"What is RAG?" → alpha=0.65 (conceptual question)

=== OUTPUT ===
Respond with ONLY valid JSON. The "reasoning" MUST describe the actual query "{last_user_msg}", not copy example text.

{{"alpha": <0.0-1.0>, "reasoning": "<1 sentence about THIS specific query>"}}
"""

        structured_llm = self.alpha_structured or self.llm.with_structured_output(AlphaEstimation)
        try:
            result = structured_llm.invoke(evaluation_prompt)

            alpha = max(0.0, min(1.0, result.alpha))
            reasoning = result.reasoning or "No reasoning provided"

            # Categorize search strategy
            if alpha <= 0.15:
                strategy = "Pure Lexical (BM25)"
            elif alpha <= 0.4:
                strategy = "Lexical-Heavy (BM25 dominant)"
            elif alpha <= 0.6:
                strategy = "Balanced (Hybrid)"
            elif alpha <= 0.75:
                strategy = "Semantic-Heavy (Vector dominant)"
            else:
                strategy = "Pure Semantic (Vector)"

            elapsed = time.time() - start_time
            logger.info(f"Query evaluation: strategy={strategy}, alpha={alpha:.2f}, elapsed={elapsed:.3f}s")
            logger.debug(f"Query evaluation details: reasoning={reasoning}, query={last_user_msg}")

            return {
                "alpha": alpha,
                "query_analysis": reasoning,
            }

        except Exception as e:
            # Fallback to default if evaluation fails
            elapsed = time.time() - start_time
            logger.warning(f"Query evaluation failed: {e}, using default alpha=0.25, elapsed={elapsed:.3f}s")
            return {
                "alpha": 0.25,
                "query_analysis": f"Evaluation failed: {str(e)}",
            }

    def _verify_and_replace_documents(
        self,
        documents: List[Document],
        min_valid_documents: int,
    ) -> List[Document]:
        """
        Verify all document links and replace broken ones.

        Args:
            documents: Retrieved documents to verify
            min_valid_documents: Maintain this many docs with valid links

        Returns:
            Documents with verified/replaced links
        """
        if not documents:
            return documents

        logger.info(f"LinkVerifier: checking {len(documents)} document links")

        # Extract all URLs from documents
        urls = []
        for doc in documents:
            url = doc.metadata.get("url")
            if url and url not in urls:
                urls.append(url)

        # Verify all URLs
        verification_results = self.link_verifier.verify_urls(urls)

        # Count results
        broken_urls = {url: reason for url, (is_valid, reason) in verification_results.items() if not is_valid}
        valid_count = len([is_valid for is_valid, _ in verification_results.values() if is_valid])
        broken_count = len(broken_urls)

        logger.info(f"LinkVerifier: {valid_count} valid, {broken_count} broken links")

        # Emit link verification event
        broken_sources = [
            doc.metadata.get("source", "unknown")
            for doc in documents
            if doc.metadata.get("url") in broken_urls
        ]

        if LinkVerificationEvent:
            try:
                event = LinkVerificationEvent(
                    total_links_checked=len(verification_results),
                    valid_links=valid_count,
                    broken_links=broken_count,
                    broken_link_sources=broken_sources,
                    cache_hits=0,  # Would need to track in LinkVerifier
                )
                self._emit_event_from_sync(event)
            except Exception as e:
                logger.debug(f"Could not emit link verification event: {e}")

        # Replace broken documents if any
        if broken_urls:
            documents, replacement_info = self.doc_replacer.replace_broken_documents(
                documents,
                verification_results,
                min_valid_documents,
            )

            # Emit replacement event
            if DocumentReplacementEvent and replacement_info:
                try:
                    event = DocumentReplacementEvent(
                        replacements_made=len(self.doc_replacer.replacement_log),
                        replacement_details=self.doc_replacer.replacement_log,
                        documents_after_replacement=len(documents),
                    )
                    self._emit_event_from_sync(event)
                except Exception as e:
                    logger.debug(f"Could not emit document replacement event: {e}")

        return documents

    def agent_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Agent response generation node - generates response from retrieved documents.

        This is a deterministic node that runs after retriever_node.
        Uses retrieved documents as context to answer the user's question.

        Features:
        - Verifies citation links (no 404s sent to LLM)
        - Replaces broken-link documents to maintain document count
        - Emits observability events for link verification
        """
        from config import ENABLE_LINK_VERIFICATION, MIN_VALID_DOCUMENTS

        start_time = time.time()
        messages = list(state["messages"])
        retrieved_documents = state.get("retrieved_documents", [])
        intent = state.get("intent", "question")
        summary_text = state.get("summary_text")

        if intent == "summary" and summary_text:
            logger.info("Agent: summary intent detected, returning cached summary")
            return {"messages": [AIMessage(content=summary_text)]}

        # Handle clarify intent - ask user for more context
        if intent == "clarify":
            clarifying_questions = state.get("clarifying_questions", [])
            # Always return clarification response, even if questions list is empty
            if clarifying_questions:
                questions_text = "\n".join(f"- {q}" for q in clarifying_questions)
                clarify_response = f"I'm not quite sure what you're asking. Could you help me understand better?\n\n{questions_text}"
            else:
                # Fallback response if no questions were generated
                clarify_response = "I'm not quite sure what you're asking. Could you please provide more details?"
            logger.info(f"Agent: clarify intent detected, asking {len(clarifying_questions)} questions")
            return {"messages": [AIMessage(content=clarify_response)]}

        logger.info(f"Agent: processing with {len(retrieved_documents)} retrieved documents")

        # Verify citation links if enabled
        if ENABLE_LINK_VERIFICATION and retrieved_documents:
            retrieved_documents = self._verify_and_replace_documents(
                retrieved_documents,
                MIN_VALID_DOCUMENTS
            )

        # Extract user query
        user_query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content
                break

        # Check if retrieval failed even after alpha refinement retry
        # If alpha was adjusted and max relevance is still very low, return honest acknowledgment
        MIN_RELEVANCE_THRESHOLD = 0.10  # Same as citation suppression threshold
        alpha_adjusted = state.get("alpha_adjusted", False)
        max_relevance = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0
        )

        if alpha_adjusted and max_relevance < MIN_RELEVANCE_THRESHOLD:
            logger.info(
                f"Agent: retrieval failed after alpha refinement "
                f"(max_relevance={max_relevance:.3f} < {MIN_RELEVANCE_THRESHOLD})"
            )
            no_info_response = (
                f"I searched the knowledge base but couldn't find any relevant information "
                f"about '{user_query or 'your question'}'. This topic may not be covered in the "
                f"available documentation.\n\n"
                f"The knowledge base contains Lucille ETL framework documentation. "
                f"If you have questions about Lucille pipelines, stages, or connectors, I'd be happy to help!"
            )
            return {"messages": [AIMessage(content=no_info_response)]}

        # Build context from retrieved documents
        if retrieved_documents:
            context_parts = []
            for i, doc in enumerate(retrieved_documents, 1):
                title = doc.metadata.get('title', '')
                source = doc.metadata.get('source', 'unknown')
                doc_type = doc.metadata.get('doc_type', 'reference')
                score = doc.metadata.get('reranker_score', 0)
                # Format: [Document N: Title] (doc_type, relevance: score)
                header = f"[Document {i}: {title}]" if title else f"[Document {i}]"
                context_parts.append(f"{header} ({doc_type}, relevance: {score:.3f})\n{doc.page_content or ''}")
            context = "\n\n---\n\n".join(context_parts)
        else:
            context = "No relevant documents were found."

        # Build citation list from retrieved documents' URLs (deduplicated)
        # Only include citations if documents have meaningful relevance scores
        citations_dict: Dict[str, Tuple[str, List[int]]] = {}  # Map URL to (label, doc_indices)

        # Check max relevance score - suppress citations if all docs are irrelevant
        max_relevance = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0
        )
        MIN_CITATION_RELEVANCE = 0.10  # Don't cite docs below 10% relevance

        if max_relevance >= MIN_CITATION_RELEVANCE:
            for i, doc in enumerate(retrieved_documents, 1):
                # Skip docs with very low relevance
                doc_score = doc.metadata.get("reranker_score", 0.0)
                if doc_score < MIN_CITATION_RELEVANCE:
                    continue

                url = doc.metadata.get("url")
                if not url:
                    continue
                # If URL already tracked, just append the doc index
                if url in citations_dict:
                    citations_dict[url][1].append(i)
                    continue
                # Use title first, fallback to extracted title from filename or path
                label = doc.metadata.get("title")
                if not label:
                    # Try to extract a readable title from filename/path
                    label = self._extract_title_from_path(
                        doc.metadata.get("source", doc.metadata.get("filename", ""))
                    )
                # If still no label, extract class/method name from source path
                if not label and "source" in doc.metadata:
                    source = doc.metadata["source"]
                    # For Java classes: "com/kmwllc/lucille/core/Connector.html" → "Connector"
                    # For markdown: "lucille-examples/README.md" → "Lucille Examples README"
                    if source.endswith(".html"):
                        # Java documentation - extract class name
                        label = source.split("/")[-1].replace(".html", "")
                    elif source.endswith(".md"):
                        # Markdown - extract from path
                        parts = source.rstrip("/").split("/")
                        # Use filename, but improve readability
                        filename = parts[-1].replace(".md", "").replace(".mdx", "")
                        if filename.lower() != "readme":
                            label = filename.replace("_", " ").replace("-", " ").title()
                        elif len(parts) > 1:
                            label = parts[-2].replace("_", " ").replace("-", " ").title()
                if not label:
                    label = "Documentation"
                citations_dict[url] = (label, [i])
        else:
            logger.info(f"Suppressing citations: max_relevance={max_relevance:.3f} < {MIN_CITATION_RELEVANCE}")

        # Convert to list format with document index prefixes
        citations = []
        for url, (label, indices) in citations_dict.items():
            index_prefix = ",".join(str(idx) for idx in indices)
            citations.append({"label": f"[{index_prefix}] {label}", "url": url})

        # Build recent conversation context (excluding the current query)
        recent_context = self._build_recent_context(messages)
        recent_context_block = f"Recent context:\n{recent_context}\n\n" if recent_context else ""

        # Create prompt with context
        # Check if this is a task-based intent (synthesis/generation requested)
        intent = state.get("intent", "question")
        is_task = intent == "task"

        if is_task:
            # For tasks, allow synthesis and generation from the knowledge base
            synthesis_instruction = """- You can synthesize and generate new content (tutorials, guides, examples) based on the retrieved documentation.
- Draw from multiple documents to create comprehensive responses.
- Clearly cite which documents you're drawing from when synthesizing."""
        else:
            # For questions, stick closer to existing documentation
            synthesis_instruction = "- Use only the retrieved documents above and the recent conversation context to respond; do not hallucinate beyond those facts."

        # Prepare mode shift context for explicit feedback (Layer 3)
        mode_shift_type = state.get("mode_shift_type", "continuation")
        previous_mode = state.get("previous_agent_mode", "rag")
        mode_shift_preamble = ""
        if mode_shift_type == "hard_shift" and previous_mode != "rag":
            mode_shift_preamble = (
                f"\n[Context: Switching from {previous_mode.replace('_', ' ')} mode to Q&A. "
                f"Acknowledge the shift naturally and respond to the new question.]\n"
            )

        system_prompt = f"""{mode_shift_preamble}You are a precise, grounded assistant that answers questions using a knowledge base of Lucille ETL framework documentation.
{recent_context_block}RETRIEVED DOCUMENTS FROM KNOWLEDGE BASE:
{context}

INSTRUCTIONS:
{synthesis_instruction}
- When drawing on a document, cite it descriptively (e.g., "According to the Pipeline class documentation..." or "As described in the Connector interface...").
- Do NOT cite as "Document N" — always use a descriptive name from the document title so readers can match citations to the Sources list.
- Always cite sources so users can verify information by reviewing the Sources section.
- If you cannot generate content due to insufficient relevant information, explain what information is missing and offer to try a different search query.
- Highlight any follow-up actions, clarifications, or uncertainties in a short summary paragraph at the end.
- Keep tone professional, concise, and helpful; respect the user's stated intent (question, task, follow-up, etc.).
"""

        # Build messages for LLM
        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query or "Please summarize the context.")
        ]

        # Generate response with streaming if available
        if hasattr(self.llm, "stream") and callable(getattr(self.llm, "stream")):
            response = self._stream_llm_response_simple(llm_messages)
        else:
            logger.debug("LLM does not support streaming, using invoke()")
            response = self.llm.invoke(llm_messages)

        # Calculate response statistics
        response_length = len(response.content) if hasattr(response, "content") else 0
        elapsed = time.time() - start_time

        logger.info(f"Agent: generated response ({response_length} chars) in {elapsed:.3f}s")

        return {"messages": [response], "citations": citations}

    def _build_recent_context(self, messages: Sequence[BaseMessage], limit: int = 6) -> str:
        """
        Format a short history block from the most recent messages (excluding the current query).
        """
        if not messages:
            return ""

        history_entries: list[str] = []
        recent_messages = list(messages)

        # Drop the current query if it's the last message (it will be appended separately)
        if recent_messages and isinstance(recent_messages[-1], HumanMessage):
            recent_messages = recent_messages[:-1]

        for msg in reversed(recent_messages):
            content = getattr(msg, "content", "")
            if not content or not str(content).strip():
                continue
            label = self._label_for_message(msg)
            history_entries.append(f"{label}: {str(content).strip()}")
            if len(history_entries) >= limit:
                break

        history_entries.reverse()
        return "\n".join(history_entries)

    def _expand_vague_query(self, query: str, messages: Sequence[BaseMessage]) -> str:
        """
        Expand vague follow-up queries using LLM and conversation context.

        Uses the lightweight alpha_estimator_llm to intelligently determine if
        a query needs expansion and what the expanded query should be.

        Args:
            query: The user's query
            messages: Conversation history

        Returns:
            Expanded query with topic context, or original query if not needed
        """
        # Build conversation context
        context = self._build_recent_context(messages, limit=4)
        if not context:
            return query

        # Check if query already contains a specific topic - skip LLM expansion
        # "What about LangSmith?" already has a topic, don't expand
        query_lower = query.lower()
        has_specific_topic = any(word[0].isupper() for word in query.split() if len(word) > 2)

        # Detect vague follow-up queries that need context expansion
        # These are queries that reference the previous topic but lack specific context
        vague_patterns = [
            # Continuation requests
            "tell me more", "go on", "continue", "what else", "elaborate",
            "expand on that", "more about that", "more info", "keep going",
            # Action requests without context (e.g., "Provide an example" after discussing Connectors)
            "provide", "show me", "give me", "make me an", "create a", "write a",
            "build a", "generate an", "design a", "implement a", "show an example"
        ]
        is_vague = any(query_lower.startswith(p) or query_lower == p for p in vague_patterns)

        # Also check if query is a pure action request without a clear topic
        # (e.g., "Provide a starter template" - no "template for what?")
        action_verbs = ["provide", "show", "give", "make", "create", "write", "build", "generate", "design", "implement"]
        starts_with_action = any(query_lower.startswith(v) for v in action_verbs)

        # If it's an action request without a specific object/topic, it's vague
        if starts_with_action and not has_specific_topic:
            is_vague = True

        if not is_vague:
            # Query has specific content, don't risk LLM hallucination
            return query

        # Use LLM only for truly vague queries
        prompt = f"""The user said "{query}" as a follow-up. Based on the conversation, what topic are they asking about?

CONVERSATION CONTEXT:
{context}

Expand the query to include the topic. Return ONLY the expanded query text.
Example: If context discusses RAG and user says "tell me more", return "tell me more about RAG"

OUTPUT:"""

        try:
            response = self.alpha_estimator_llm.invoke(prompt)
            expanded = response.content.strip() if hasattr(response, "content") else str(response).strip()

            # Remove any quotes the LLM might have added
            expanded = expanded.strip('"\'')

            # Sanity check - don't accept empty or very long expansions
            if not expanded or len(expanded) > 500:
                return query

            if expanded != query:
                logger.info(f"Query expansion: '{query}' → '{expanded}'")
                # Emit query expansion event
                if QueryExpansionEvent:
                    try:
                        self._emit_event_from_sync(QueryExpansionEvent(
                            original_query=query,
                            expanded_query=expanded,
                            expansion_reason=f"Vague follow-up expanded using conversation context"
                        ))
                    except Exception as emit_error:
                        logger.debug(f"Could not emit query expansion event: {emit_error}")

            return expanded
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}, using original query")
            return query

    def _classify_intent(self, user_input: str, messages: Sequence[BaseMessage]) -> tuple[str, str, float, list]:
        """
        Classify user intent using LLM.

        Returns:
            Tuple of (intent, reasoning, confidence, clarifying_questions)
            - intent: The classified intent (question, summary, follow_up, clarify)
            - reasoning: Explanation for the classification
            - confidence: 0.0-1.0 confidence score
            - clarifying_questions: List of questions to ask if confidence is low
        """
        from config import ENABLE_CONFIG_BUILDER, ENABLE_DOC_WRITER

        prompt = self._build_intent_prompt(user_input, messages)

        structured_llm = self.intent_structured or self.llm.with_structured_output(IntentClassification)
        try:
            result = structured_llm.invoke(prompt)
            intent = result.intent.strip().lower()
            reasoning = result.reasoning
            confidence = result.confidence
            clarifying_questions = result.clarifying_questions

            # If confidence is below threshold, switch to clarify intent
            CONFIDENCE_THRESHOLD = 0.7
            if confidence < CONFIDENCE_THRESHOLD and clarifying_questions:
                logger.info(f"Low confidence ({confidence:.2f}), will ask for clarification")
                return "clarify", reasoning, confidence, clarifying_questions

            return intent, reasoning, confidence, clarifying_questions
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return "question", f"Classification failed, defaulting to question: {str(e)[:50]}", 0.5, []


    def _build_intent_prompt(self, user_input: str, messages: Sequence[BaseMessage]) -> str:
        from config import ENABLE_CONFIG_BUILDER, ENABLE_DOC_WRITER

        history_block = self._build_recent_context(messages, limit=6)

        # Build available intents list based on feature flags
        available_intents = ["question", "summary", "follow_up"]
        if ENABLE_CONFIG_BUILDER:
            available_intents.insert(1, "config_request")
        if ENABLE_DOC_WRITER:
            available_intents.insert(2 if ENABLE_CONFIG_BUILDER else 1, "documentation_request")

        intents_str = "|".join(available_intents)

        # Build example format with first available intent
        example_intent = available_intents[0] if available_intents else "question"

        prompt = f"""Classify user intent. Return ONLY valid JSON.

CRITICAL - CHECK THESE KEYWORDS FIRST (in order):
1. Is message vague expansion/continuation ("add more", "tell me more", "show more", "expand", "elaborate", "more detail", "more about", "more on")? → follow_up (ALWAYS)
2. Is message a short acknowledgment (<5 words: "ok", "got it", "thanks", "understood", "i see", "interesting", "perfect")? → follow_up (ALWAYS)
3. Does message contain "summarize", "recap", "summary"? → summary (ALWAYS)
4. Does message contain "pipeline"? → config_request (ALWAYS)
5. Does message contain "config" or "HOCON"? → config_request (ALWAYS)
6. Does message contain "write", "create", "document", "draft", "tutorial", "guide", "article", "blog" as ACTION VERBS? → documentation_request (ALWAYS)
7. None of above? → question (DEFAULT)

SPECIAL CASE: "Document X" or "Write X" or "Create X" is ALWAYS documentation_request, even if short.

IMPORTANT:
- "Build me a X to Y pipeline" is ALWAYS config_request because it contains "pipeline"
- "Write a tutorial/guide/article" is documentation_request (publication-ready content)
- "How do I X?" or "What is X?" is question (conversational Q&A)

AVAILABLE INTENTS: {intents_str}

OUTPUT FORMAT:
{{
  "intent": "{example_intent}",  // MUST be one of: {intents_str}
  "reasoning": "Brief explanation",
  "confidence": 0.0-1.0,
  "clarifying_questions": ["Question 1?", "Question 2?"]  // Only if confidence < 0.7
}}

CLASSIFICATION RULES:
1. QUESTION: User is requesting information or asking for explanation (conversational Q&A)
   - Includes: "How about X?", "What about X?", "Tell me about X?", "What is X?"
   - Any message that could be rephrased as a question
   - Examples: "How do I use X?", "What are the benefits?", "Explain how X works"
   - Key: Conversational questions expecting direct answers, NOT multi-section publications
   - This is the DEFAULT intent for most queries"""

        # Only include CONFIG_REQUEST rules if feature is enabled
        if ENABLE_CONFIG_BUILDER:
            prompt += """

2. CONFIG_REQUEST: User wants a Lucille pipeline configuration generated
   - TRIGGER KEYWORD: "pipeline" anywhere in message → ALWAYS this intent
   - Other keywords: "config", "HOCON", "configuration file"
   - Examples that MUST be config_request:
     * "Build me a CSV to Solr pipeline"
     * "Create a pipeline with CopyFields"
     * "Generate a pipeline configuration"
   - If you see "pipeline", classify as config_request immediately"""

        # Only include DOCUMENTATION_REQUEST rules if feature is enabled
        if ENABLE_DOC_WRITER:
            rule_num = 3 if ENABLE_CONFIG_BUILDER else 2
            prompt += f"""

{rule_num}. DOCUMENTATION_REQUEST: User wants multi-section content for publication
   - Includes: API documentation, tutorials, guides, how-to articles, blog posts
   - Action verbs: "write", "create", "document", "draft", "compose"
   - Content types: "tutorial", "guide", "article", "blog post", "documentation", "reference"
   - Examples:
     * "Write a tutorial on how to create a pipeline"
     * "Create a guide for beginners"
     * "Write documentation for the CSVConnector"
     * "Document all available stages"
     * "Write an article about search optimization"
   - Key: If requesting structured, publication-ready content → documentation_request"""

        # Continue with remaining rules
        rule_num = 2
        if ENABLE_CONFIG_BUILDER:
            rule_num += 1
        if ENABLE_DOC_WRITER:
            rule_num += 1

        prompt += f"""

{rule_num}. SUMMARY: User explicitly requests a recap/summary of the conversation
   - Requires keywords: "summarize", "recap", "summary", "what have we covered"
   - Must be about the CONVERSATION itself, not about a topic
   - Examples: "Summarize what we discussed", "Recap the conversation"

{rule_num + 1}. FOLLOW_UP: Vague continuation/expansion requests that need conversation context
   - HIGHEST PRIORITY PATTERN: Action verbs without explicit subjects
   - Vague expansion requests: "add more detail", "tell me more", "show more", "expand on that", "give me examples", "provide more information"
   - Vague references: "more about that", "more on this", "expand it", "elaborate", "go deeper"
   - Short acknowledgments: "ok", "got it", "thanks", "understood", "i see", "interesting", "perfect", "great"
   - Key indicators:
     * Action verb (add, show, tell, expand, give, provide) WITHOUT specific subject
     * Vague pronouns (that, this, it, more) requiring context
     * Request only makes sense with conversation history
   - Examples:
     * "Add more detail" (detail about WHAT? Needs context!)
     * "Tell me more" (more about WHAT?)
     * "Expand on that" (on WHAT?)
     * "Show me examples" (examples of WHAT?)
     * "Give me more information" (information about WHAT?)
     * "OK", "Got it", "Thanks"

PRIORITY ORDER - Check in this exact order:
1. SUMMARY if "summarize", "recap", or "summary" present"""

        priority_num = 2
        if ENABLE_CONFIG_BUILDER:
            prompt += f"""
{priority_num}. CONFIG_REQUEST if "pipeline", "config", or "HOCON" present"""
            priority_num += 1

        if ENABLE_DOC_WRITER:
            prompt += f"""
{priority_num}. DOCUMENTATION_REQUEST if requesting publication content ("write", "create", "tutorial", "guide", "article", "blog", "document")"""
            priority_num += 1

        prompt += f"""
{priority_num}. FOLLOW_UP if very short acknowledgment (<5 words: "ok", "got it", "thanks", "understood", "i see", "interesting")
{priority_num + 1}. QUESTION for everything else (DEFAULT)

CONFIDENCE GUIDELINES:
- 0.9-1.0: Very clear intent, unambiguous message
- 0.7-0.9: Reasonably clear, minor ambiguity
- 0.5-0.7: Ambiguous, could be interpreted multiple ways
- 0.0-0.5: Very unclear, need more context

IF CONFIDENCE < 0.7:
- Provide 1-3 clarifying questions in "clarifying_questions" array
- Questions should help disambiguate the user's intent
- Keep questions concise and specific

USER MESSAGE: "{user_input}"

CONVERSATION HISTORY:
{history_block or 'No prior context.'}

Respond with JSON only. No other text."""
        return prompt

    def _label_for_message(self, message: BaseMessage) -> str:
        if isinstance(message, HumanMessage):
            return "User"
        if isinstance(message, AIMessage):
            return "Assistant"
        if isinstance(message, ToolMessage):
            tool_name = getattr(message, "tool_name", "tool")
            return f"Tool:{tool_name}"
        if isinstance(message, SystemMessage):
            return "System"
        return "Message"

    def _detect_mode_shift(self, state: CustomAgentState, new_intent: str) -> str:
        """
        Determine the type of mode shift implied by the new intent relative to prior state.

        Returns one of:
          "continuation" — same mode as before, or first turn (no prior mode)
          "soft_shift"   — ambiguous transition; follow_up after a non-RAG mode
          "hard_shift"   — explicit new mode via a mode-specific intent keyword

        Intent-to-mode mapping:
          question, follow_up, summary, clarify → "rag"
          config_request                        → "config_builder"
          documentation_request                 → "doc_writer"

        The caller (intent_classifier_node) is responsible for writing
        previous_agent_mode and mode_shift_type back to state.
        """
        _INTENT_TO_MODE = {
            "question": "rag",
            "follow_up": "rag",
            "summary": "rag",
            "clarify": "rag",
            "config_request": "config_builder",
            "documentation_request": "doc_writer",
        }

        current_mode = state.get("agent_mode") or "rag"
        new_mode = _INTENT_TO_MODE.get(new_intent, "rag")

        # First turn or same mode
        if current_mode == new_mode:
            return "continuation"

        # follow_up after a non-RAG mode: user may still be in that context
        if new_intent == "follow_up" and current_mode != "rag":
            return "soft_shift"

        # Explicit mode-specific intent keyword pointing to a different mode
        # or RAG-flavored intent after a non-RAG mode
        return "hard_shift"

    def _extract_title_from_path(self, path: str) -> str:
        """
        Extract a readable title from a file path.

        Examples:
        - src/oss/python/concepts/langchain.md → "LangChain Concepts"
        - src/oss/python/integrations/llms/moonshot.mdx → "Moonshot LLM Integration"
        - docs/how-to/vector_stores.md → "Vector Stores How-To"
        """
        if not path:
            return ""

        # Extract filename without extension
        import os
        filename = os.path.splitext(os.path.basename(path))[0]

        # Skip common non-document filenames
        if filename in ("index", "readme", "_", "__"):
            return ""

        # Convert snake_case/kebab-case to Title Case
        title = filename.replace("_", " ").replace("-", " ")

        # Add context from parent directories if helpful
        parts = path.split("/")
        if len(parts) >= 2:
            parent_dir = parts[-2].lower()
            # Add doc type suffix from path
            if parent_dir in ("concepts", "conceptual"):
                title = f"{title.title()} Concepts"
            elif parent_dir in ("how-to", "how_to"):
                title = f"{title.title()} How-To"
            elif parent_dir == "tutorials":
                title = f"{title.title()} Tutorial"
            elif parent_dir in ("quickstart", "getting-started", "getting_started"):
                title = f"{title.title()} Quickstart"
            elif parent_dir == "integrations":
                title = f"{title.title()} Integration"
            elif parent_dir == "llms":
                title = f"{title.title()} LLM"
            elif parent_dir == "tools":
                title = f"{title.title()} Tool"
            elif parent_dir == "chat_models":
                title = f"{title.title()} Chat Model"
            else:
                title = title.title()
        else:
            title = title.title()

        return title

    def _stream_llm_response_simple(self, messages: Sequence[BaseMessage]) -> AIMessage:
        """
        Stream the LLM response and accumulate the full response while emitting events.

        Simplified version without tool binding - for direct response generation.

        Args:
            messages: The input messages for the LLM

        Returns:
            The accumulated AIMessage response
        """
        stream_start = time.time()

        # Emit start event (if event classes are available)
        if LLMResponseStartEvent is not None:
            start_event = LLMResponseStartEvent()
            self._emit_streaming_event(start_event)

        # Accumulate response content
        accumulated_content = ""
        chunk_count = 0

        try:
            # Stream from the LLM
            for chunk in self.llm.stream(messages):
                chunk_count += 1

                # Extract content from chunk
                if hasattr(chunk, "content") and chunk.content:
                    accumulated_content += chunk.content

                    # Emit chunk event (if event classes are available)
                    if LLMResponseChunkEvent is not None:
                        chunk_event = LLMResponseChunkEvent(content=chunk.content, is_complete=False)
                        self._emit_streaming_event(chunk_event)

        except StopIteration:
            pass
        except RuntimeError as e:
            if "StopIteration" not in str(e):
                logger.warning(f"RuntimeError during LLM streaming: {e}. Falling back to invoke.")
        except Exception as e:
            logger.warning(f"Exception during LLM streaming: {e}. Falling back to invoke.")

        # If streaming produced no content, fall back to invoke
        if not accumulated_content:
            invoke_result = self.llm.invoke(messages)
            if hasattr(invoke_result, "content"):
                accumulated_content = invoke_result.content if invoke_result.content else ""
            else:
                accumulated_content = str(invoke_result)

        # Emit completion event (if event classes are available)
        if LLMResponseChunkEvent is not None:
            completion_event = LLMResponseChunkEvent(content="", is_complete=True)
            self._emit_streaming_event(completion_event)

        stream_elapsed = time.time() - stream_start
        logger.debug(f"Streaming complete: {chunk_count} chunks, {len(accumulated_content)} chars in {stream_elapsed:.3f}s")

        return AIMessage(content=accumulated_content)

    def _emit_streaming_event(self, event) -> None:
        """
        Emit a streaming event (for future integration with WebSocket or event listeners).

        Currently logs the event. Can be extended to:
        - Send events to WebSocket clients
        - Broadcast to observability systems
        - Update real-time dashboards

        Args:
            event: The streaming event to emit
        """
        if event is None:
            return

        if LLMResponseStartEvent is not None and isinstance(event, LLMResponseStartEvent):
            logger.debug("LLM streaming started")
        elif LLMResponseChunkEvent is not None and isinstance(event, LLMResponseChunkEvent):
            if event.is_complete:
                logger.debug("LLM streaming complete")
            else:
                logger.debug(f"LLM chunk received: {len(event.content)} chars")

    def _emit_event_from_sync(self, event) -> None:
        """
        Emit an event from a synchronous context immediately.

        This is called from retriever_node to emit intermediate events
        (hybrid search result, reranker start) as they happen.

        Uses asyncio.run_coroutine_threadsafe to schedule the emit in the
        running event loop without blocking.
        """
        if not self.emit_callback or not self.event_loop:
            return

        try:
            import asyncio
            # Use the stored event loop that was set when emit_callback was assigned
            asyncio.run_coroutine_threadsafe(self.emit_callback(event), self.event_loop)
            # Don't wait for the result - let it run asynchronously
        except Exception as e:
            # Fallback: queue the event if we can't emit directly
            logger.debug(f"Could not emit event immediately: {e}, queueing instead")
            self.event_queue.append(event)

    def summary_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Generate a conversation summary when the user intent is to summarize history.
        """
        intent = state.get("intent", "question")
        messages = state["messages"]
        if intent != "summary":
            return {"summary_text": None, "message_count": len(messages)}

        logger.info(f"Generating summary for {len(messages)} messages")
        summary_text = self.summarize_messages(messages)
        if not summary_text:
            summary_text = "No additional context available for summary."
        return {"summary_text": summary_text, "message_count": len(messages)}

    def retriever_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Automatic retrieval node - performs hybrid search + reranking.

        This is a deterministic node that always runs after query_evaluator.
        No LLM involvement - uses original query (or rewritten query for retries) with dynamic alpha.

        Increments retrieval_attempts counter for Phase 4 iterative retrieval tracking.
        """
        start_time = time.time()
        messages = state["messages"]
        alpha = state.get("alpha", 0.25)
        intent = state.get("intent", "question")

        # Increment attempt counter (Phase 4)
        attempts = state.get("retrieval_attempts", 1)
        new_attempts = attempts + 1

        # Early exit for summary intent - no retrieval needed
        if intent == "summary":
            logger.debug("Retriever: skipping hybrid search because intent is summary")
            return {"retrieved_documents": [], "retrieval_attempts": new_attempts}

        # Use rewritten query if available (Phase 4), otherwise use original
        query = state.get("query_transformed")
        if not query:
            # Extract original user query from messages
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    query = msg.content
                    break

        # Expand vague follow-up queries using conversation context
        if query:
            query = self._expand_vague_query(query, messages)

        if not query:
            logger.warning("Retriever: no user query found in messages")
            return {"retrieved_documents": [], "retrieval_attempts": new_attempts}

        logger.info(f"Retriever: query='{query[:50]}...', alpha={alpha:.2f}")

        # Emit embedding progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(SearchProgressEvent(
                    stage="embedding",
                    message="Embedding query..."
                ))
            except Exception as e:
                logger.debug(f"Could not emit embedding progress event: {e}")

        # Create retriever with dynamic alpha
        retriever = self.vector_store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": RERANKER_FETCH_K if ENABLE_RERANKING else RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": alpha
            }
        )

        # Emit search progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(SearchProgressEvent(
                    stage="vector_search",
                    message="Searching vector index..."
                ))
            except Exception as e:
                logger.debug(f"Could not emit vector search progress event: {e}")

        # Get initial results
        retrieve_start = time.time()
        results = retriever.invoke(query)
        retrieve_elapsed = time.time() - retrieve_start

        logger.info(f"Retriever: retrieved {len(results)} documents in {retrieve_elapsed:.3f}s")

        # Emit text search progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(SearchProgressEvent(
                    stage="text_search",
                    message="Full-text search complete"
                ))
            except Exception as e:
                logger.debug(f"Could not emit text search progress event: {e}")

        # Emit fusion progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(SearchProgressEvent(
                    stage="fusion",
                    message="Fusing results with Reciprocal Rank Fusion..."
                ))
            except Exception as e:
                logger.debug(f"Could not emit fusion progress event: {e}")

        # Emit hybrid search result event
        if HybridSearchResultEvent and results:
            try:
                search_event = HybridSearchResultEvent(
                    candidate_count=len(results),
                    candidates=[
                        SearchCandidate(
                            source=doc.metadata.get("source", "unknown"),
                            snippet=doc.page_content[:200] + "..." if doc.page_content and len(doc.page_content) > 200 else doc.page_content or "",
                            url=doc.metadata.get("url"),
                        )
                        for doc in results[:10]
                    ],
                )
                self._emit_event_from_sync(search_event)
            except Exception as e:
                logger.debug(f"Could not emit hybrid search result event: {e}")

        # Apply reranking if enabled
        if ENABLE_RERANKING and self.reranker and results:
            # Emit reranker start event
            if RerankerStartEvent:
                try:
                    reranker_event = RerankerStartEvent(
                        model=RERANKER_MODEL,
                        candidate_count=len(results),
                    )
                    self._emit_event_from_sync(reranker_event)
                except Exception as e:
                    logger.debug(f"Could not emit reranker start event: {e}")
            # Store original ranks
            original_sources = [doc.metadata.get('source', 'unknown') for doc in results]
            for i, doc in enumerate(results, 1):
                doc.metadata['original_rank'] = i

            # Calculate total content size for throughput metrics
            total_content_chars = sum(len(doc.page_content) if doc.page_content else 0 for doc in results)
            batch_size = self.reranker.batch_size
            num_batches = (len(results) + batch_size - 1) // batch_size

            rerank_start = time.time()
            logger.info(f"Reranker: processing {len(results)} candidates, batch_size={batch_size}, device={self.reranker.device}")

            # Emit initial progress
            if RerankerProgressEvent:
                try:
                    self._emit_event_from_sync(RerankerProgressEvent(
                        stage="scoring",
                        progress=0.0,
                        message=f"Scoring {len(results)} documents..."
                    ))
                except Exception as e:
                    logger.debug(f"Could not emit reranker progress event: {e}")

            reranked_results = self.reranker.rerank(query, results, RERANKER_TOP_K)
            rerank_elapsed = time.time() - rerank_start

            # Emit completion progress
            if RerankerProgressEvent:
                try:
                    self._emit_event_from_sync(RerankerProgressEvent(
                        stage="ranking",
                        progress=1.0,
                        message=f"Ranking complete - {len(results)} documents scored"
                    ))
                except Exception as e:
                    logger.debug(f"Could not emit reranker completion event: {e}")

            # Extract documents with scores
            results_with_scores = [(doc, score) for doc, score in reranked_results]
            results = [doc for doc, score in results_with_scores]

            # Store reranker scores in metadata
            for i, (doc, score) in enumerate(results_with_scores, 1):
                doc.metadata['reranker_score'] = score

            # Calculate throughput metrics
            docs_per_sec = len(results) / rerank_elapsed if rerank_elapsed > 0 else 0
            chars_per_sec = total_content_chars / rerank_elapsed if rerank_elapsed > 0 else 0
            ms_per_doc = (rerank_elapsed * 1000) / len(results) if results else 0

            # Log reranking results with detailed timing
            avg_score = sum(score for _, score in results_with_scores) / len(results_with_scores) if results_with_scores else 0
            logger.info(f"Reranker: complete in {rerank_elapsed:.3f}s, top {len(results)} selected, avg_score={avg_score:.4f}")
            logger.debug(f"Reranker throughput: {docs_per_sec:.1f} docs/s, {chars_per_sec:.0f} chars/s, {ms_per_doc:.1f} ms/doc")

            # Log individual scores at debug level
            for i, (doc, score) in enumerate(results_with_scores, 1):
                source = doc.metadata.get('source', 'unknown')
                logger.debug(f"  {i}. score={score:.4f} [{source}]")

            # Log order changes
            reranked_sources = [doc.metadata.get('source', 'unknown') for doc in results]
            if original_sources[:len(reranked_sources)] != reranked_sources:
                logger.debug("Reranker: order changed (reranking improved relevance)")
            else:
                logger.debug("Reranker: order unchanged (already optimally ranked)")
        else:
            logger.debug("Retriever: no reranking (disabled or no documents)")

        elapsed = time.time() - start_time
        logger.info(f"Retriever: total time {elapsed:.3f}s")

        # Store initial results before any alpha adjustment (for comparison after retry)
        # Only store if this is the first retrieval (alpha_adjusted is not True)
        return_state: Dict[str, Any] = {
            "retrieved_documents": results,
            "retrieval_attempts": new_attempts
        }

        if not state.get("alpha_adjusted", False):
            # First retrieval - save results for later comparison
            max_score = max(
                (doc.metadata.get("reranker_score", 0.0) for doc in results),
                default=0.0
            )
            return_state["_initial_retrieved_documents"] = results
            return_state["_initial_max_score"] = max_score
            logger.debug(f"Retriever: stored initial results (max_score={max_score:.3f})")

        return return_state

    def alpha_refiner_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Check if retrieval results have low relevance and retry with adjusted alpha.

        This node implements Phase 3: single retry strategy with alpha adjustment.
        - If max reranker_score < ALPHA_REFINEMENT_THRESHOLD and not already adjusted
        - Adjust alpha based on strategy and trigger retrieval retry
        - Otherwise, pass through to agent

        Args:
            state: Current agent state with retrieved documents

        Returns:
            Updated state with potentially adjusted alpha
        """
        from config import ENABLE_ALPHA_REFINEMENT, ALPHA_REFINEMENT_THRESHOLD

        current_alpha = state.get("alpha", DEFAULT_ALPHA)

        # Early return if refinement disabled
        if not ENABLE_ALPHA_REFINEMENT:
            return {
                "alpha_adjusted": False,
                "_needs_retrieval_retry": False,
                "alpha_refinement_reason": "Refinement disabled in config",
                "original_alpha": current_alpha,
                "max_score": 0.0
            }

        # Early return if already adjusted (prevent multiple retries)
        if state.get("alpha_adjusted", False):
            # Compare retry results with initial results - keep the better one
            retrieved_documents = state.get("retrieved_documents", [])
            retry_max_score = max(
                (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
                default=0.0
            )

            initial_documents = state.get("_initial_retrieved_documents", [])
            initial_max_score = state.get("_initial_max_score", 0.0)

            # Choose the better results
            if initial_max_score > retry_max_score and initial_documents:
                # Initial was better - restore it
                logger.info(
                    f"AlphaRefiner: initial results better "
                    f"(initial={initial_max_score:.3f} > retry={retry_max_score:.3f}), restoring initial"
                )
                return {
                    "_needs_retrieval_retry": False,
                    "alpha_refinement_reason": f"Kept initial results (score {initial_max_score:.3f} > retry {retry_max_score:.3f})",
                    "original_alpha": current_alpha,
                    "max_score": initial_max_score,
                    "retrieved_documents": initial_documents,  # Restore initial results
                }
            else:
                # Retry was better or equal - keep retry results
                logger.info(
                    f"AlphaRefiner: retry results better or equal "
                    f"(retry={retry_max_score:.3f} >= initial={initial_max_score:.3f}), keeping retry"
                )
                return {
                    "_needs_retrieval_retry": False,
                    "alpha_refinement_reason": f"Kept retry results (score {retry_max_score:.3f} >= initial {initial_max_score:.3f})",
                    "original_alpha": current_alpha,
                    "max_score": retry_max_score
                }

        retrieved_documents = state.get("retrieved_documents", [])

        # No documents to evaluate
        if not retrieved_documents:
            return {
                "alpha_adjusted": False,
                "_needs_retrieval_retry": False,
                "alpha_refinement_reason": "No documents to evaluate",
                "original_alpha": current_alpha,
                "max_score": 0.0
            }

        # Get max reranker score
        max_score = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0
        )

        # Check if refinement is needed
        if max_score >= ALPHA_REFINEMENT_THRESHOLD:
            return {
                "alpha_adjusted": False,
                "_needs_retrieval_retry": False,
                "alpha_refinement_reason": f"Max score {max_score:.3f} above threshold {ALPHA_REFINEMENT_THRESHOLD}",
                "original_alpha": current_alpha,
                "max_score": max_score
            }

        # Refinement triggered - adjust alpha toward the OPPOSITE end
        # If initial search was semantic-heavy and failed, try lexical (and vice versa)
        if current_alpha >= 0.5:
            # Was semantic-heavy, try lexical
            new_alpha = max(0.0, current_alpha - 0.4)
            direction = "lexical"
        else:
            # Was lexical-heavy, try semantic
            new_alpha = min(1.0, current_alpha + 0.4)
            direction = "semantic"

        logger.info(f"AlphaRefiner: low relevance (max_score={max_score:.3f}), adjusting alpha {current_alpha:.2f} → {new_alpha:.2f} ({direction}-boost)")

        return {
            "alpha": new_alpha,
            "alpha_adjusted": True,
            "_needs_retrieval_retry": True,  # Signal router to retry retrieval
            "alpha_refinement_reason": f"Triggered by low max score ({max_score:.3f}) - adjusted to {new_alpha:.2f}",
            "original_alpha": current_alpha,
            "max_score": max_score
        }

    def _route_after_intent(self, state: CustomAgentState) -> str:
        """Route based on detected intent.

        Returns the route key from intent_routes mapping, not the node name.
        Intent routes mapping:
        - "clarify" → agent node (direct clarification response)
        - "summary" → summary node (skip retrieval)
        - "config_builder" → config_resolver node (config pipeline)
        - "doc_writer" → content_type_classifier or doc_planner node (doc pipeline)
        - "other" → query_evaluator node (normal Q&A pipeline)

        Special cases:
        - If awaiting_clarification=True (from previous turn), route to clarification resolver
          UNLESS a hard_shift was detected (user abandoned the clarification context)
        - If soft_shift follow_up is detected, route back to the previous mode's handler
        """
        from config import ENABLE_CONFIG_BUILDER, ENABLE_DOC_WRITER, ENABLE_CONTENT_TYPE_CLASSIFICATION

        intent = state.get("intent", "question")
        shift_type = state.get("mode_shift_type", "continuation")
        previous_mode = state.get("previous_agent_mode", "rag")

        # Check if we're awaiting user's clarification response
        # But skip this if a hard_shift was detected (user abandoned the clarification context)
        if state.get("awaiting_clarification") and shift_type != "hard_shift":
            clarification_type = state.get("clarification_type", "format")
            if clarification_type == "format" and ENABLE_CONTENT_TYPE_CLASSIFICATION:
                logger.info("User responding to format clarification")
                return "format_resolver"
            elif clarification_type == "topic" and ENABLE_CONTENT_TYPE_CLASSIFICATION:
                logger.info("User responding to topic clarification")
                return "topic_resolver"

        # Handle soft_shift: follow_up while in a non-RAG mode should stay in that mode
        if shift_type == "soft_shift" and intent == "follow_up":
            logger.info(
                f"Soft shift: follow_up after {previous_mode} mode — "
                f"routing back to {previous_mode}"
            )
            if previous_mode == "config_builder" and ENABLE_CONFIG_BUILDER:
                return "config_builder"
            if previous_mode == "doc_writer" and ENABLE_DOC_WRITER:
                return "doc_writer"
            # fallthrough to "other" if the previous mode is unavailable


        # Handle disabled features - remap to question for RAG processing
        if intent == "config_request" and not ENABLE_CONFIG_BUILDER:
            logger.info(f"Config builder disabled - remapping config_request to question")
            state["intent"] = "question"
            intent = "question"

        if intent == "documentation_request" and not ENABLE_DOC_WRITER:
            logger.info(f"Doc writer disabled - remapping documentation_request to question")
            state["intent"] = "question"
            intent = "question"

        # Route based on intent - MUST return the KEY from intent_routes, not the node name
        if intent == "clarify":
            return "clarify"  # Key in intent_routes; maps to "agent" node
        if intent == "summary":
            return "summary"  # Key in intent_routes; maps to "summary" node
        if intent == "config_request" and ENABLE_CONFIG_BUILDER:
            return "config_builder"  # Key in intent_routes; maps to "config_resolver" node
        if intent == "documentation_request" and ENABLE_DOC_WRITER:
            return "doc_writer"  # Key in intent_routes; maps to content classifier/planner
        return "other"  # Key in intent_routes; maps to "query_evaluator" node

    def _route_after_config_validation(self, state: CustomAgentState) -> str:
        """Route based on config validation result.

        Returns:
        - "valid": config passed validation, proceed to response
        - "retry": config failed, retries remaining, go back to generator
        - "max_retries": config failed, no retries left, proceed to response with errors
        """
        from config import CONFIG_VALIDATION_MAX_RETRIES

        passed = state.get("config_validation_passed", False)
        attempts = state.get("config_validation_attempts", 0)

        if passed:
            return "valid"
        elif attempts < CONFIG_VALIDATION_MAX_RETRIES:
            return "retry"
        else:
            return "max_retries"

    def _route_after_query_evaluator(self, state: CustomAgentState) -> str:
        """Route after query evaluator to retriever.

        Query evaluator only runs for intents that need search (question, follow_up, task).
        Summary intents skip query_evaluator entirely (routed directly to summary node).
        Clarify intents skip both query_evaluator and go straight to agent.
        Config/doc requests skip query_evaluator entirely.
        """
        return "retriever"

    def _route_after_summary(self, state: CustomAgentState) -> str:
        """Route after summary node.

        If intent was summary, go directly to agent (skip retrieval).
        Otherwise continue to retriever.
        """
        intent = state.get("intent", "question")
        if intent == "summary":
            return "done"
        return "continue"

    def _should_retry_retrieval(self, state: CustomAgentState) -> str:
        """Determine if alpha refinement should retry retrieval.

        Uses _needs_retrieval_retry transient signal to prevent infinite loops.
        This signal is only True when alpha was JUST adjusted this pass.
        """
        if state.get("_needs_retrieval_retry", False):
            return "retry"
        return "continue"

    def _route_after_content_type_classifier(self, state: CustomAgentState) -> str:
        """Route after content type classification.

        Checks if clarification is needed (awaiting_clarification=True).
        If yes, returns END to wait for user's clarification response.
        If no, routes to appropriate content generator.
        """
        if state.get("awaiting_clarification"):
            logger.info("Content type clarification needed, waiting for user response")
            return END

        # Otherwise, route by content type
        return self._route_by_content_type(state)

    def _route_by_content_type(self, state: CustomAgentState) -> str:
        """Route based on detected content type.

        Returns semantic route KEYS that map to appropriate generators:
        - "social" → social_content_generator
        - "blog" → blog_content_generator
        - "article" → article_content_generator
        - "tutorial" → tutorial_generator
        - "comprehensive" → doc_planner (existing pipeline)

        Default: "comprehensive" (comprehensive documentation)

        This function follows the same pattern as other routing functions,
        returning semantic keys that are mapped to node names in conditional_edges.
        """
        content_type = state.get("content_type", "comprehensive_docs")

        # Map content types to semantic route keys
        # These keys are resolved to actual node names in conditional_edges dicts
        routing_map = {
            "social_post": "social",
            "blog_post": "blog",
            "technical_article": "article",
            "tutorial": "tutorial",
            "comprehensive_docs": "comprehensive",
        }

        route = routing_map.get(content_type, "comprehensive")
        logger.info(f"Routing content type '{content_type}' to '{route}'")
        return route

    def confidence_evaluator_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Evaluate retrieval confidence based on reranker scores (Phase 4).

        Checks if top result has sufficient relevance. If confidence is low,
        triggers query rewriting and retry.

        Only active if ENABLE_ITERATIVE_RETRIEVAL is true.

        Args:
            state: Current agent state with retrieved documents

        Returns:
            Updated state with confidence metrics and potential retry trigger
        """
        from config import (
            ENABLE_ITERATIVE_RETRIEVAL, CONFIDENCE_THRESHOLD,
            MAX_RETRIEVAL_ATTEMPTS
        )

        # Early return if iterative retrieval disabled
        if not ENABLE_ITERATIVE_RETRIEVAL:
            return {}

        retrieved_documents = state.get("retrieved_documents", [])

        # No documents to evaluate
        if not retrieved_documents:
            return {
                "confidence_score": 0.0,
                "low_confidence_reason": "No documents retrieved"
            }

        # Get max reranker score
        max_score = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0
        )

        attempts = state.get("retrieval_attempts", 1)

        # Check if confidence is sufficient
        if max_score >= CONFIDENCE_THRESHOLD:
            logger.debug(f"ConfidenceEvaluator: confidence sufficient (max_score={max_score:.3f})")
            return {
                "confidence_score": max_score,
                "low_confidence_reason": None
            }

        # Check if we can retry
        if attempts >= MAX_RETRIEVAL_ATTEMPTS:
            logger.info(f"ConfidenceEvaluator: low confidence ({max_score:.3f}) but max attempts ({MAX_RETRIEVAL_ATTEMPTS}) reached")
            return {
                "confidence_score": max_score,
                "low_confidence_reason": f"Low confidence ({max_score:.3f}) but max attempts reached"
            }

        # Low confidence and can retry
        logger.info(f"ConfidenceEvaluator: low confidence ({max_score:.3f}) - will rewrite query")
        return {
            "confidence_score": max_score,
            "low_confidence_reason": f"Score {max_score:.3f} below threshold {CONFIDENCE_THRESHOLD}"
        }

    def query_rewriter_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Rewrite query for improved retrieval when confidence is low (Phase 4).

        Uses lightweight LLM to suggest better query formulation.
        Only called if iterative retrieval is enabled and confidence is low.

        Args:
            state: Current agent state with low confidence results

        Returns:
            Updated state with rewritten query and incremented attempt counter
        """
        from config import ENABLE_ITERATIVE_RETRIEVAL, QUERY_REWRITER_MODEL

        # Early return if iterative retrieval disabled
        if not ENABLE_ITERATIVE_RETRIEVAL:
            return {}

        # Extract original query
        messages = state["messages"]
        original_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                original_query = msg.content if hasattr(msg, "content") else ""
                break

        if not original_query:
            return {}

        confidence_score = state.get("confidence_score", 0.0)
        reason = state.get("low_confidence_reason", "")
        attempts = state.get("retrieval_attempts", 1)

        # Build rewrite prompt
        prompt = f"""The initial search returned low-confidence results.
Original query: "{original_query}"
Confidence issue: {reason}

Rewrite this query to improve retrieval. Consider:
- Adding more specific terms or context
- Removing ambiguous words
- Using synonyms or related concepts
- Reframing the question if needed

Return ONLY the rewritten query, nothing else."""

        logger.info(f"QueryRewriter: rewriting query (attempt {attempts})")

        try:
            # Use same rewriter model as query evaluator
            if not hasattr(self, 'query_rewriter_llm') or self.query_rewriter_llm is None:
                self.query_rewriter_llm = ChatGoogleGenerativeAI(
                    model=QUERY_REWRITER_MODEL,
                    temperature=0,
                )

            response = self.query_rewriter_llm.invoke(prompt)
            transformed_query = response.content.strip() if hasattr(response, "content") else str(response)

            logger.info(f"QueryRewriter: original='{original_query[:50]}...', rewritten='{transformed_query[:50]}...'")

            return {
                "query_transformed": transformed_query,
                "retrieval_attempts": attempts + 1
            }
        except Exception as e:
            logger.warning(f"Query rewriting failed ({e}), continuing with original query")
            return {
                "query_transformed": original_query,
                "retrieval_attempts": attempts + 1
            }

    def _should_continue_or_rewrite(self, state: CustomAgentState) -> str:
        """Determine if confidence is low enough to trigger query rewrite"""
        from config import ENABLE_ITERATIVE_RETRIEVAL, MAX_RETRIEVAL_ATTEMPTS

        if not ENABLE_ITERATIVE_RETRIEVAL:
            return "continue"

        low_confidence_reason = state.get("low_confidence_reason")
        attempts = state.get("retrieval_attempts", 1)

        if low_confidence_reason and attempts < MAX_RETRIEVAL_ATTEMPTS:
            return "rewrite"
        return "continue"

    def create_agent_graph(self):
        """Create custom StateGraph with automatic retrieval pipeline.

        Base flow: intent_classifier → query_evaluator → summary → retriever → alpha_refiner → agent → END

        Config builder flow: intent_classifier → config_resolver → config_generator → config_response → END
        Doc writer flow: intent_classifier → doc_planner → doc_gatherer → doc_synthesizer → END

        With Phase 4 enabled:
          - Adds confidence_evaluator after alpha_refiner
          - Adds query_rewriter for low-confidence results
          - Implements retrieval retry loop

        Phases:
        - Phase 1: Intent classification (always on)
        - Phase 2: Progress events (always on)
        - Phase 3: Alpha refinement (configurable, default enabled)
        - Phase 4: Iterative retrieval (configurable, default disabled)
        """
        from config import ENABLE_ITERATIVE_RETRIEVAL, ENABLE_CONFIG_BUILDER, ENABLE_DOC_WRITER

        logger.info("Creating agent graph with automatic retrieval")

        # Build the graph
        workflow = StateGraph(CustomAgentState)

        # Add core nodes (always present)
        workflow.add_node("intent_classifier", self.intent_classifier_node)
        workflow.add_node("query_evaluator", self.query_evaluator_node)
        workflow.add_node("summary", self.summary_node)
        workflow.add_node("retriever", self.retriever_node)
        workflow.add_node("alpha_refiner", self.alpha_refiner_node)

        # Add Phase 4 nodes (conditional)
        if ENABLE_ITERATIVE_RETRIEVAL:
            workflow.add_node("confidence_evaluator", self.confidence_evaluator_node)
            workflow.add_node("query_rewriter", self.query_rewriter_node)

        workflow.add_node("agent", self.agent_node)

        # Add Config Builder nodes (Phase 2)
        if ENABLE_CONFIG_BUILDER:
            from config_builder import (
                config_resolver_node, config_generator_node,
                config_validator_node, config_response_node,
            )
            workflow.add_node("config_resolver", lambda state: config_resolver_node(state, self))
            workflow.add_node("config_generator", lambda state: config_generator_node(state, self))
            workflow.add_node("config_validator", lambda state: config_validator_node(state, self))
            workflow.add_node("config_response", lambda state: config_response_node(state, self))

        # Add Documentation Writer nodes (Phase 3)
        if ENABLE_DOC_WRITER:
            from config import ENABLE_CONTENT_TYPE_CLASSIFICATION
            from doc_writer import doc_planner_node, doc_gatherer_node, doc_synthesizer_node

            # Add content type classifier if enabled
            if ENABLE_CONTENT_TYPE_CLASSIFICATION:
                from content_generators import (
                    content_type_classifier_node,
                    format_clarification_resolver_node,
                    topic_clarification_resolver_node,
                    social_content_generator_node,
                    blog_content_generator_node,
                    article_content_generator_node,
                    tutorial_generator_node,
                )

                workflow.add_node("content_type_classifier", lambda state: content_type_classifier_node(state, self))
                workflow.add_node("format_clarification_resolver", lambda state: format_clarification_resolver_node(state, self))
                workflow.add_node("topic_clarification_resolver", lambda state: topic_clarification_resolver_node(state, self))
                workflow.add_node("social_content_generator", lambda state: social_content_generator_node(state, self))
                workflow.add_node("blog_content_generator", lambda state: blog_content_generator_node(state, self))
                workflow.add_node("article_content_generator", lambda state: article_content_generator_node(state, self))
                workflow.add_node("tutorial_generator", lambda state: tutorial_generator_node(state, self))

            # Add comprehensive doc writer nodes
            workflow.add_node("doc_planner", lambda state: doc_planner_node(state, self))
            workflow.add_node("doc_gatherer", lambda state: doc_gatherer_node(state, self))
            workflow.add_node("doc_synthesizer", lambda state: doc_synthesizer_node(state, self))

        # Set entry point
        workflow.set_entry_point("intent_classifier")

        # Build routing map for intent classifier
        intent_routes = {"summary": "summary", "clarify": "agent", "other": "query_evaluator"}
        if ENABLE_CONFIG_BUILDER:
            intent_routes["config_builder"] = "config_resolver"
        if ENABLE_DOC_WRITER:
            from config import ENABLE_CONTENT_TYPE_CLASSIFICATION
            # Route to classifier first if enabled, otherwise directly to doc_planner
            if ENABLE_CONTENT_TYPE_CLASSIFICATION:
                intent_routes["doc_writer"] = "content_type_classifier"
                intent_routes["format_resolver"] = "format_clarification_resolver"
                intent_routes["topic_resolver"] = "topic_clarification_resolver"
            else:
                intent_routes["doc_writer"] = "doc_planner"

        # Add core edges with conditional routing
        workflow.add_conditional_edges(
            "intent_classifier",
            self._route_after_intent,
            intent_routes,
        )
        workflow.add_edge("query_evaluator", "retriever")
        workflow.add_conditional_edges(
            "summary",
            self._route_after_summary,
            {"done": "agent", "continue": "retriever"}
        )
        workflow.add_edge("retriever", "alpha_refiner")

        # Alpha refiner routing (Phase 3)
        workflow.add_conditional_edges(
            "alpha_refiner",
            self._should_retry_retrieval,
            {"retry": "retriever", "continue": "confidence_evaluator" if ENABLE_ITERATIVE_RETRIEVAL else "agent"}
        )

        # Phase 4 routing (if enabled)
        if ENABLE_ITERATIVE_RETRIEVAL:
            workflow.add_conditional_edges(
                "confidence_evaluator",
                self._should_continue_or_rewrite,
                {"rewrite": "query_rewriter", "continue": "agent"}
            )
            workflow.add_edge("query_rewriter", "retriever")

        # Config builder edges (with validation-retry loop)
        if ENABLE_CONFIG_BUILDER:
            workflow.add_edge("config_resolver", "config_generator")
            workflow.add_edge("config_generator", "config_validator")
            workflow.add_conditional_edges(
                "config_validator",
                self._route_after_config_validation,
                {
                    "valid": "config_response",
                    "retry": "config_generator",
                    "max_retries": "config_response",
                }
            )
            workflow.add_edge("config_response", END)

        # Documentation writer edges
        if ENABLE_DOC_WRITER:
            from config import ENABLE_CONTENT_TYPE_CLASSIFICATION

            # Content type classifier routes to appropriate generator (or END if clarification needed)
            if ENABLE_CONTENT_TYPE_CLASSIFICATION:
                workflow.add_conditional_edges(
                    "content_type_classifier",
                    self._route_after_content_type_classifier,
                    {
                        "social": "social_content_generator",
                        "blog": "blog_content_generator",
                        "article": "article_content_generator",
                        "tutorial": "tutorial_generator",
                        "comprehensive": "doc_planner",
                        END: END,  # When clarification is needed
                    }
                )

                # Format clarification resolver routes to appropriate generator
                workflow.add_conditional_edges(
                    "format_clarification_resolver",
                    self._route_by_content_type,
                    {
                        "social": "social_content_generator",
                        "blog": "blog_content_generator",
                        "article": "article_content_generator",
                        "tutorial": "tutorial_generator",
                        "comprehensive": "doc_planner",
                    }
                )

                # Topic resolver routes to appropriate generator
                workflow.add_conditional_edges(
                    "topic_clarification_resolver",
                    self._route_by_content_type,
                    {
                        "social": "social_content_generator",
                        "blog": "blog_content_generator",
                        "article": "article_content_generator",
                        "tutorial": "tutorial_generator",
                        "comprehensive": "doc_planner",
                    }
                )

                # Lightweight generators → END
                workflow.add_edge("social_content_generator", END)
                workflow.add_edge("blog_content_generator", END)
                workflow.add_edge("article_content_generator", END)
                workflow.add_edge("tutorial_generator", END)

            # Comprehensive docs → existing pipeline
            workflow.add_edge("doc_planner", "doc_gatherer")
            workflow.add_edge("doc_gatherer", "doc_synthesizer")
            workflow.add_edge("doc_synthesizer", END)

        # Agent is the final step for RAG pipeline
        workflow.add_edge("agent", END)

        # Compile with checkpointer
        self.app = workflow.compile(checkpointer=self.checkpointer)

        # Log graph structure
        modes = ["RAG"]
        if ENABLE_CONFIG_BUILDER:
            modes.append("Config Builder")
        if ENABLE_DOC_WRITER:
            modes.append("Doc Writer")
        logger.info(f"Agent graph created with modes: {', '.join(modes)}")

    def generate_thread_id(self):
        """Generate a unique thread ID for conversation persistence"""
        self.thread_id = f"conversation_{uuid.uuid4().hex[:8]}"

    def set_thread_id(self, thread_id: str):
        """Set a specific thread ID to resume a conversation"""
        self.thread_id = thread_id

    def _ensure_metadata_table(self):
        """Ensure the conversation_metadata table exists.

        Creates the conversation_metadata table if it doesn't already exist.
        This table stores conversation titles and timestamps for the conversation list.

        Raises:
            Does not raise exceptions - logs warnings if table creation fails.
        """
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversation_metadata (
                            thread_id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Could not create conversation_metadata table: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating conversation_metadata table: {e}")

    def list_conversations(self):
        """List available previous conversations from PostgreSQL with titles"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Query the metadata table for conversations with titles
                    cur.execute("""
                        SELECT thread_id, title, created_at
                        FROM conversation_metadata
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                    conversations = cur.fetchall()
                    return conversations
        except Exception as e:
            print(f"Error listing conversations: {e}")
            return []

    def clear_all_conversations(self):
        """Clear all previous conversations from the database"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    # Delete all conversation metadata
                    cur.execute("DELETE FROM conversation_metadata")
                    metadata_count = cur.rowcount

                    # Delete all checkpoints (conversation history)
                    cur.execute("DELETE FROM checkpoints")
                    checkpoint_count = cur.rowcount

                    # Delete checkpoint blobs if they exist
                    try:
                        cur.execute("DELETE FROM checkpoint_blobs")
                    except psycopg.Error:
                        pass  # Table may not exist, which is acceptable

                    return metadata_count, checkpoint_count
        except Exception as e:
            print(f"Error clearing conversations: {e}")
            return 0, 0

    def generate_conversation_title(self, messages: List[BaseMessage]) -> str:
        """Use the LLM to generate a concise title for the conversation.

        Analyzes the conversation messages and generates a descriptive title
        that captures the main topic being discussed.

        Args:
            messages: List of conversation messages to analyze.

        Returns:
            A concise title (max 50 characters). Returns a default title if
            generation fails or no suitable messages are found.

        Raises:
            Does not raise exceptions - returns fallback titles on error.
        """
        try:
            # Build a summary of the conversation for title generation
            conversation_summary = []
            for msg in messages[-6:]:  # Use last 6 messages for context
                if hasattr(msg, "content") and msg.content:
                    # Safely get message type
                    role = "User" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                    content = str(msg.content)[:200]  # Truncate long messages
                    conversation_summary.append(f"{role}: {content}")

            if not conversation_summary:
                return "New Conversation"

            prompt = f"""Generate a very short title (max 50 chars) for this conversation.
The title should capture the main topic or question being discussed.
Return ONLY the title, nothing else.

Conversation:
{chr(10).join(conversation_summary)}

Title:"""

            response = self.llm.invoke(prompt)
            title = response.content.strip().strip('"\'')[:50]
            return title if title else "Untitled Conversation"
        except Exception as e:
            logger.debug(f"Title generation failed, using fallback: {e}")
            # Fallback: use first user message
            for msg in messages:
                if hasattr(msg, "type") and msg.type == "human" and hasattr(msg, "content") and msg.content:
                    return str(msg.content)[:50].strip()
            return "Untitled Conversation"

    def update_conversation_title(self):
        """Generate and save a title for the current conversation based on its content.

        Retrieves the current conversation messages from the checkpoint, generates
        a descriptive title using the LLM, and stores it in the conversation_metadata table.

        This method is called after each agent response to keep the title up-to-date
        with the conversation content.

        Raises:
            Does not raise exceptions - logs warnings if title update fails.
        """
        try:
            # Get current conversation messages from checkpoint
            checkpoint = self.checkpointer.get({"configurable": {"thread_id": self.thread_id}})
            if not checkpoint:
                logger.debug("No checkpoint found for title update")
                return

            # Access messages from channel_values (checkpoint is a dict)
            channel_values = checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                logger.debug("No messages in checkpoint for title update")
                return

            # Generate title from conversation
            title = self.generate_conversation_title(messages)

            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Insert or update conversation metadata with new title
                    cur.execute("""
                        INSERT INTO conversation_metadata (thread_id, title)
                        VALUES (%s, %s)
                        ON CONFLICT (thread_id)
                        DO UPDATE SET title = EXCLUDED.title, updated_at = CURRENT_TIMESTAMP
                    """, (self.thread_id, title))
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Database error updating conversation title: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating conversation title: {e}")

    def estimate_token_count(self, messages: Sequence[BaseMessage]) -> int:
        """
        Estimate token count for a list of messages.
        Uses 1 token ≈ 4 characters heuristic (conservative for English).

        Args:
            messages: Sequence of BaseMessage objects to estimate token count for.

        Returns:
            Estimated token count based on character length.
        """
        try:
            total_chars = 0
            for msg in messages:
                if hasattr(msg, "content") and msg.content:
                    total_chars += len(str(msg.content))
            return total_chars // TOKEN_CHAR_RATIO
        except Exception:
            return 0

    def _fallback_summarize(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Create a simple fallback summary when LLM summarization fails.
        Uses basic heuristics to extract key information without LLM.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A simple summary of the conversation.
        """
        if not messages_to_summarize:
            return "No earlier context"

        # Extract user questions and assistant topics
        user_topics = []
        assistant_topics = []

        for msg in messages_to_summarize:
            if hasattr(msg, "content") and msg.content:
                content_preview = str(msg.content)[:100].strip()
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)
                else:
                    if "human" in str(type(msg)).lower():
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)

        # Build simple summary
        summary_parts = [f"Earlier conversation ({len(messages_to_summarize)} messages):"]

        if user_topics:
            summary_parts.append(f"User asked about: {', '.join(user_topics[:3])}")
            if len(user_topics) > 3:
                summary_parts.append(f"(and {len(user_topics) - 3} more topics)")

        if assistant_topics:
            summary_parts.append(f"Assistant discussed: {', '.join(assistant_topics[:3])}")
            if len(assistant_topics) > 3:
                summary_parts.append(f"(and {len(assistant_topics) - 3} more topics)")

        return ". ".join(summary_parts)

    def summarize_messages(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Use LLM to create a concise summary of older messages.
        Preserves key facts and context while being brief.
        Falls back to simple summaries if LLM fails.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A concise summary of the message content.
        """
        if not messages_to_summarize:
            return "No earlier context"

        try:
            # Build context of messages to summarize
            context = ""
            for msg in messages_to_summarize:
                if hasattr(msg, "content") and msg.content:
                    # Determine role from message type
                    if hasattr(msg, "type"):
                        role = "User" if msg.type == "human" else "Assistant"
                    else:
                        role = "Assistant" if "assistant" in str(type(msg)).lower() else "User"
                    context += f"{role}: {msg.content}\n\n"

            if not context.strip():
                return "No earlier context"

            # Prompt LLM to summarize
            summary_prompt = f"""Summarize the following conversation concisely in 1-2 paragraphs, preserving key facts and context.
Focus on what the user asked, what the assistant already provided, and whether any next steps remain.
Mention any uncertainties or missing pieces so the user knows what's incomplete.

Conversation:
{context}

Summary:"""

            # Invoke LLM for summary (direct, not through agent)
            response = self.llm.invoke(summary_prompt)
            return response.content if hasattr(response, "content") else str(response)

        except httpx.ConnectError as e:
            logger.error(
                f"Connection error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True
            )
            logger.info("Falling back to simple concatenation summary")
            return self._fallback_summarize(messages_to_summarize)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"JSON/parsing error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True
            )
            logger.info("Falling back to word count summary")
            return self._fallback_summarize(messages_to_summarize)

        except TimeoutError as e:
            logger.error(
                f"Timeout while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True
            )
            logger.info("Falling back to first/last message summary")
            # Get first and last messages
            first_msg = ""
            last_msg = ""
            if messages_to_summarize:
                if hasattr(messages_to_summarize[0], "content"):
                    first_msg = str(messages_to_summarize[0].content)[:80]
                if hasattr(messages_to_summarize[-1], "content"):
                    last_msg = str(messages_to_summarize[-1].content)[:80]
            summary = f"Earlier conversation ({len(messages_to_summarize)} messages): "
            if first_msg:
                summary += f"Started with: {first_msg}. "
            if last_msg:
                summary += f"Ended with: {last_msg}"
            return summary

        except Exception as e:
            logger.error(
                f"Unexpected error while summarizing {len(messages_to_summarize)} messages: {type(e).__name__}: {e}",
                exc_info=True
            )
            logger.info("Falling back to basic summary")
            return self._fallback_summarize(messages_to_summarize)

    def compact_conversation_if_needed(self, messages: Sequence[BaseMessage]) -> Tuple[Sequence[BaseMessage], bool, int]:
        """
        Check if conversation needs compaction and compact if necessary.

        Args:
            messages: Sequence of messages to check for compaction.

        Returns:
            Tuple of (compacted_messages, was_compacted, num_compacted) where:
            - compacted_messages: The potentially compacted message sequence
            - was_compacted: Boolean indicating if compaction occurred
            - num_compacted: Number of messages that were compacted
        """
        if not ENABLE_COMPACTION or not messages:
            return messages, False, 0

        if len(messages) < MIN_MESSAGES_FOR_COMPACTION:
            return messages, False, 0

        # Estimate token count
        token_count = self.estimate_token_count(messages)
        threshold = int(MAX_CONTEXT_TOKENS * COMPACTION_THRESHOLD_PCT)

        if token_count < threshold:
            return messages, False, 0  # No compaction needed

        # Perform compaction
        messages_to_keep = messages[-MESSAGES_TO_KEEP_FULL:]
        messages_to_compact = messages[:-MESSAGES_TO_KEEP_FULL]

        # Generate summary
        summary_text = self.summarize_messages(messages_to_compact)

        # Create summary message
        summary_msg = SystemMessage(
            content=f"[Earlier conversation summary]: {summary_text}"
        )

        # Return compacted messages
        compacted = [summary_msg] + messages_to_keep
        num_compacted = len(messages_to_compact)

        # Log compaction completion with token counts
        compacted_token_count = self.estimate_token_count(compacted)
        logger.info(
            f"Compacted {num_compacted} messages "
            f"(token count: {compacted_token_count}/{MAX_CONTEXT_TOKENS})"
        )

        return compacted, True, num_compacted

    def run_conversation(self):
        """Run the interactive conversation loop"""
        print("=" * 70)
        print("Lucille Documentation Agent - Local Knowledge Base & Memory")
        print("=" * 70)
        print()
        print("Agent is ready! You can ask questions about:")
        print("  - Python programming basics")
        print("  - Machine learning concepts")
        print("  - Web development")
        print()
        print("Commands:")
        print("  - Type your question and press Enter")
        print("  - Type 'new' to start a new conversation")
        print("  - Type 'list' to see previous conversations")
        print("  - Type 'load <id>' to resume a conversation")
        print("  - Type 'clear' to delete all conversations")
        print("  - Type 'quit' or 'exit' to stop")
        print()
        print("=" * 70)
        print()

        self.generate_thread_id()
        print(f"Conversation ID: {self.thread_id}")
        print("(Title will be updated after each message)")
        print()

        while True:
            try:
                # Get user input
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                # Handle special commands
                if user_input.lower() == "quit" or user_input.lower() == "exit":
                    print("\nGoodbye!")
                    break

                if user_input.lower() == "new":
                    self.generate_thread_id()
                    print(f"\n✓ New conversation started")
                    print(f"Conversation ID: {self.thread_id}")
                    print()
                    continue

                if user_input.lower() == "list":
                    print("\n📋 Previous Conversations:")
                    conversations = self.list_conversations()
                    if conversations:
                        for i, (thread_id, title, created_at) in enumerate(conversations, 1):
                            # Format the date nicely
                            date_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "Unknown"
                            print(f"  {i}. {title}")
                            print(f"     ID: {thread_id} | {date_str}")
                        print("\nUse 'load <id>' to resume a conversation")
                    else:
                        print("  No previous conversations found")
                    print()
                    continue

                if user_input.lower().startswith("load "):
                    thread_id = user_input[5:].strip()
                    if thread_id:
                        self.set_thread_id(thread_id)
                        print(f"\n✓ Loaded conversation: {thread_id}")
                        print()
                    else:
                        print("\n✗ Please provide a conversation ID: load <id>")
                        print()
                    continue

                if user_input.lower() == "clear":
                    # Confirm before clearing
                    confirm = input("\n⚠️  This will delete ALL conversations and history. Continue? (yes/no): ").strip().lower()
                    if confirm == "yes":
                        metadata_count, checkpoint_count = self.clear_all_conversations()
                        print(f"\n✓ Cleared {metadata_count} conversation(s) and {checkpoint_count} checkpoint record(s)")
                    else:
                        print("✗ Clear cancelled")
                    print()
                    continue

                # Process the input through the agent
                print()
                self._invoke_agent(user_input)
                print()

            except KeyboardInterrupt:
                print("\n\nInterrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\n✗ Error: {e}")
                print("Try again or type 'quit' to exit\n")

    def _invoke_agent(self, user_input: str):
        """
        Invoke the agent with user input and stream intermediate reasoning steps.

        This method uses modern LangGraph streaming to show:
        1. Agent reasoning and decision-making steps
        2. Tool calls to the knowledge base with intermediate results
        3. Final response streamed character-by-character for real-time feedback

        Args:
            user_input: The user's question or command
        """
        try:
            # Prepare input for the agent with new state schema
            input_data = {
                "messages": [],
                "alpha": 0.25,  # Default alpha (will be set by query_evaluator_node)
                "query_analysis": "",
                "intent": "question",
                "summary_text": None,
            }

            # Try to apply compaction to conversation if needed
            compacted_messages: List[BaseMessage] = []
            current_messages: Sequence[BaseMessage] = []
            try:
                checkpoint_state = self.checkpointer.get({"configurable": {"thread_id": self.thread_id}})
                if checkpoint_state and "messages" in checkpoint_state:
                    current_messages = checkpoint_state["messages"]
                    compacted_msgs, was_compacted, num_compacted = self.compact_conversation_if_needed(current_messages)
                    compacted_messages = list(compacted_msgs)
                    if was_compacted:
                        print(f"[🗜️  Compacted {num_compacted} older messages to maintain context]")
            except Exception:
                # If compaction fails, just continue without it
                compacted_messages = []

            if not compacted_messages:
                compacted_messages = list(current_messages) if current_messages else []

            # Include compaction summary + history before the new user message
            history_messages = compacted_messages + [HumanMessage(content=user_input)]
            input_data["messages"] = history_messages

            final_response = ""

            # Get the current message count before invoking
            try:
                checkpoint_before = self.checkpointer.get({"configurable": {"thread_id": self.thread_id}})
                messages_before_count = len(checkpoint_before.get("messages", [])) if checkpoint_before else 0
            except Exception:
                messages_before_count = 0

            # Invoke the agent to get the complete response
            result = self.app.invoke(
                input_data,
                config={"configurable": {"thread_id": self.thread_id}},
            )

            # Log query analysis for debugging (optional)
            if "query_analysis" in result and result["query_analysis"]:
                print(f"[Debug] Query Analysis: {result['query_analysis']}")
            if "alpha" in result:
                print(f"[Debug] Lambda used: {result.get('alpha', 'N/A'):.2f}")

            # Extract final response and reasoning from result
            if "messages" in result:
                messages = result["messages"]
                # Only look at messages added in this turn (after the user message)
                # We need to find the assistant message that came after the last user input
                new_messages = messages[messages_before_count:] if messages_before_count < len(messages) else []

                # Find the last assistant message in the new messages (final response)
                for msg in reversed(new_messages):
                    if hasattr(msg, "content") and msg.content:
                        content = str(msg.content)
                        # Skip messages that are tool calls
                        if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                            final_response = content
                            break

            # Display the final response with streaming
            if final_response:
                print("Agent (response):")
                self._stream_text(final_response)
            else:
                print("Agent: Processing complete")

            # Update conversation title after each turn
            self.update_conversation_title()

        except httpx.ConnectError as e:
            print(f"✗ Cannot connect to Google AI API")
            print(f"  Error: {e}")
            print(f"\n  To fix:")
            print(f"  1. Check that GOOGLE_API_KEY is set correctly")
            print(f"  2. Verify internet connectivity")
        except Exception as e:
            print(f"✗ Error invoking agent: {e}")
            import traceback
            traceback.print_exc()

    def _stream_text(self, text: str, chunk_size: int = 1) -> None:
        """
        Display text output from LLM response without artificial delays.

        Previously used character-by-character delays for simulated streaming.
        Now displays text immediately as it's received from true LLM streaming.

        Args:
            text: The text to display to the console.
            chunk_size: Not used in current implementation (kept for compatibility).
        """
        # Display text immediately without artificial delays
        # True streaming happens via _stream_llm_response and LLM chunk events
        print(text)
        print()  # Final newline

    def run(self):
        """Main entry point for the agent"""
        try:
            self.verify_prerequisites()
            self.initialize_components()
            self.create_agent_graph()
            self.run_conversation()
        except KeyboardInterrupt:
            print("\n\nShutdown requested.")
        except Exception as e:
            print(f"\n✗ Fatal error: {e}")
            sys.exit(1)
        finally:
            self.cleanup()

    async def ensure_async_pool_open(self):
        """Ensure the async pool is open and checkpointer is created. Call this before using astream_events."""
        if self.async_pool:
            try:
                # Open the pool if not already open
                # The pool's open() method is idempotent, so calling it twice is safe
                await self.async_pool.open()
            except Exception as e:
                logger.warning(f"Error opening async pool: {e}")

        # Create checkpointer if not already created (must be done in async context)
        if self.checkpointer is None:
            from config import CHECKPOINT_SELECTIVE_SERIALIZATION
            if CHECKPOINT_SELECTIVE_SERIALIZATION:
                from checkpoint_optimizer import SelectiveJsonPlusSerializer
                self.checkpointer = AsyncPostgresSaver(self.async_pool, serde=SelectiveJsonPlusSerializer())
            else:
                self.checkpointer = AsyncPostgresSaver(self.async_pool)

            # Recompile the graph with the new checkpointer
            if self.app is not None:
                self._recompile_with_checkpointer()

    def _recompile_with_checkpointer(self):
        """Recompile the agent graph with the async checkpointer.

        This rebuilds the LangGraph workflow and compiles it with the checkpointer
        that was created asynchronously. Must be called after self.checkpointer is set.
        """
        # Reuse create_agent_graph which already handles all node/edge setup
        # and compiles with self.checkpointer
        self.create_agent_graph()
        logger.info("Graph recompiled with async checkpointer")

    async def close_async_pool(self):
        """Close the async pool."""
        if self.async_pool:
            await self.async_pool.close()

    def cleanup(self):
        """Clean up resources"""
        # Clear reranker from memory if loaded
        if self.reranker:
            del self.reranker

        if self.pool:
            self.pool.close()

        # Note: async_pool should be closed via close_async_pool() in async context


def main():
    """Main function"""
    agent = LucilleAgent()
    agent.run()


if __name__ == "__main__":
    main()
