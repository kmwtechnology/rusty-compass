"""
Agent state types for LangGraph custom agent.

Contains TypedDict definitions for the simplified agent state schema.

IMPORTANT: State fields may not be initialized. Always use state.get(key, default)
to access optional fields safely. Only 'messages' is guaranteed to exist.
"""

from typing import Sequence, List, Annotated, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.documents import Document
from langgraph.graph import add_messages


class CustomAgentState(TypedDict, total=False):
    """
    State schema for custom agent graph with dynamic alpha.

    Uses a custom TypedDict instead of MessagesState to enable independent
    control of vector/full-text search weighting (alpha) based on query
    classification.

    Flow: query_evaluator → retriever → alpha_refiner → agent

    IMPORTANT: Not all fields are guaranteed to exist at runtime.
    Use state.get(key, default) for safe access:
        - state.get("alpha", 0.25) instead of state["alpha"]
        - state.get("retrieval_attempts", 1) instead of state["retrieval_attempts"]
        - state.get("alpha_adjusted", False) instead of state["alpha_adjusted"]

    Required fields (always exist after first node):
        - messages: Conversation history

    Optional fields (may not exist until set by a node):
        - alpha, query_analysis, intent, summary_text
        - retrieved_documents
        - alpha_adjusted, alpha_refinement_reason
        - retrieval_attempts, confidence_score, low_confidence_reason, query_transformed
    """
    # Core message state (required - managed by add_messages reducer)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Intent classification state
    # Defaults: intent="question", intent_confidence=1.0
    intent: str
    intent_confidence: float  # 0.0-1.0, triggers clarify if < 0.7
    reasoning: str  # Explanation for classification
    user_query: str  # Extracted user query
    clarifying_questions: List[str]  # Questions to ask if confidence is low

    # Query evaluation state - alpha controls hybrid search balance
    # Defaults: alpha=0.25 (DEFAULT_ALPHA), query_analysis=""
    alpha: float
    query_analysis: str
    summary_text: Optional[str]

    # Retrieved documents from automatic retrieval
    # Default: empty list
    retrieved_documents: List[Document]

    # Alpha refinement state (Phase 3)
    # Defaults: alpha_adjusted=False, _needs_retrieval_retry=False
    alpha_adjusted: bool
    alpha_refinement_reason: Optional[str]
    _needs_retrieval_retry: bool  # Transient signal for routing (prevents infinite loops)
    _initial_retrieved_documents: List[Document]  # Stored before retry for comparison
    _initial_max_score: float  # Max score from initial search (before retry)

    # Iterative retrieval state (Phase 4)
    # Defaults: retrieval_attempts=1
    retrieval_attempts: int
    confidence_score: Optional[float]
    low_confidence_reason: Optional[str]
    query_transformed: Optional[str]

    # Multi-capability agent mode
    # Defaults: agent_mode="rag"
    agent_mode: Optional[str]  # "rag", "config_builder", "doc_writer"

    # Config builder state (Phase 2)
    config_components: Optional[List[dict]]  # Resolved component specs
    config_output: Optional[str]  # Generated HOCON config
    config_validation_notes: Optional[List[str]]  # Validation issues/notes

    # Documentation writer state (Phase 3)
    doc_outline: Optional[List[dict]]  # Planned sections
    doc_gathered_content: Optional[dict]  # Content gathered per section
    doc_sections_gathered: Optional[int]  # Progress tracking
    doc_sections_total: Optional[int]  # Total sections planned

    # Content type classification state (multi-format generation)
    content_type: Optional[str]  # "social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"
    content_type_confidence: Optional[float]  # 0.0-1.0 confidence in classification
    content_target_length: Optional[int]  # Target word count for generated content
    content_tone: Optional[str]  # Writing tone (engaging, narrative, technical, instructional, reference)
    content_retrieval_depth: Optional[int]  # Number of retrieval passes (1-5)
    content_temperature: Optional[float]  # LLM temperature for content generation (0.3-0.8)
    content_output: Optional[str]  # Generated content output

    # Human-in-the-loop clarification state
    needs_clarification: Optional[bool]  # True if classifier needs user input
    clarification_type: Optional[str]  # "content_type", "intent", etc.
    clarification_candidates: Optional[List[tuple]]  # Top N candidates [(type, confidence), ...]
    awaiting_clarification: Optional[bool]  # True while waiting for user response
