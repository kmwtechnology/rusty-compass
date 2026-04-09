"""
Pydantic models for WebSocket events.

These events are streamed in real-time as the agent executes,
providing full observability into every step and decision.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Annotated

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# TYPE ALIASES FOR BOUNDED SCORES
# ============================================================================

# Score bounded to [0.0, 1.0] - represents confidence/relevance
ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0, description="Score in range [0.0, 1.0]")]

# Alpha bounded to [0.0, 1.0] - represents lexical vs semantic weight
AlphaWeight = Annotated[float, Field(ge=0.0, le=1.0, description="Alpha weight: 0.0=lexical, 1.0=semantic")]

# Progress bounded to [0.0, 1.0]
ProgressPercent = Annotated[float, Field(ge=0.0, le=1.0, description="Progress percentage [0.0, 1.0]")]


# ============================================================================
# BASE EVENT
# ============================================================================


class BaseEvent(BaseModel):
    """Base class for all WebSocket events."""

    type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    node: Optional[str] = None  # Current graph node name

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ============================================================================
# CONNECTION EVENTS
# ============================================================================


class ConnectionEstablished(BaseEvent):
    """Sent when WebSocket connection is established."""

    type: Literal["connection_established"] = "connection_established"
    thread_id: str
    existing_messages: int = 0


class ConnectionError(BaseEvent):
    """Sent when connection fails."""

    type: Literal["connection_error"] = "connection_error"
    error: str


# ============================================================================
# NODE LIFECYCLE EVENTS
# ============================================================================


class NodeStartEvent(BaseEvent):
    """Emitted when a graph node starts execution."""

    type: Literal["node_start"] = "node_start"
    node: str
    input_summary: Optional[str] = None


class NodeEndEvent(BaseEvent):
    """Emitted when a graph node completes execution."""

    type: Literal["node_end"] = "node_end"
    node: str
    duration_ms: float
    output_summary: Optional[str] = None


# ============================================================================
# CONVERSATION CONTEXT EVENTS
# ============================================================================


class ConversationContextEvent(BaseEvent):
    """Emitted when conversation context is loaded from checkpoint."""

    type: Literal["conversation_context"] = "conversation_context"
    previous_message_count: int
    is_new_conversation: bool
    summary: Optional[str] = None  # e.g., "Loaded 6 previous messages"


# ============================================================================
# QUERY EVALUATOR EVENTS
# ============================================================================


class QueryEvaluationEvent(BaseEvent):
    """Emitted when query is evaluated for search strategy."""

    type: Literal["query_evaluation"] = "query_evaluation"
    node: Literal["query_evaluator"] = "query_evaluator"
    query: str
    alpha: AlphaWeight  # 0.0 (lexical) to 1.0 (semantic), validated at construction
    query_analysis: str  # LLM's reasoning
    search_strategy: Literal["lexical-heavy", "balanced", "semantic-heavy"]  # Validated set of strategies

    @field_validator("search_strategy", mode="after")
    @classmethod
    def validate_strategy_matches_alpha(cls, strategy: str, info) -> str:
        """Ensure search strategy is consistent with alpha value."""
        alpha = info.data.get("alpha", 0.5)
        # Lexical-heavy for alpha < 0.3, balanced for 0.3-0.7, semantic-heavy for > 0.7
        if alpha < 0.3 and strategy != "lexical-heavy":
            raise ValueError(f"alpha={alpha} suggests lexical-heavy search, not '{strategy}'")
        elif 0.3 <= alpha < 0.7 and strategy != "balanced":
            raise ValueError(f"alpha={alpha} suggests balanced search, not '{strategy}'")
        elif alpha >= 0.7 and strategy != "semantic-heavy":
            raise ValueError(f"alpha={alpha} suggests semantic-heavy search, not '{strategy}'")
        return strategy


class IntentClassificationEvent(BaseEvent):
    """Emitted when the intent classifier determines the user goal."""

    type: Literal["intent_classification"] = "intent_classification"
    node: Literal["intent_classifier"] = "intent_classifier"
    intent: str
    user_query: str
    reasoning: str
    confidence: Optional[ConfidenceScore] = None  # 0.0-1.0 confidence score, validated


class QueryExpansionEvent(BaseEvent):
    """Emitted when a vague query is expanded using conversation context."""

    type: Literal["query_expansion"] = "query_expansion"
    node: Literal["retriever"] = "retriever"
    original_query: str
    expanded_query: str
    expansion_reason: str


class AlphaRefinementEvent(BaseEvent):
    """Emitted when alpha is adjusted due to low relevance scores."""

    type: Literal["alpha_refinement"] = "alpha_refinement"
    node: Literal["alpha_refiner"] = "alpha_refiner"
    triggered: bool
    original_alpha: AlphaWeight  # Validated to [0.0, 1.0]
    new_alpha: Optional[AlphaWeight] = None  # Validated to [0.0, 1.0] if set
    max_score: ConfidenceScore  # Validated to [0.0, 1.0]
    threshold: ConfidenceScore  # Validated to [0.0, 1.0]
    reason: str


class SummaryEvent(BaseEvent):
    """Emitted when a summary is generated (or skipped) for conversational history."""

    type: Literal["summary_generated"] = "summary_generated"
    node: Literal["summary"] = "summary"
    summary_text: Optional[str]
    message_count: int


# ============================================================================
# HYBRID SEARCH EVENTS
# ============================================================================


class HybridSearchStartEvent(BaseEvent):
    """Emitted when hybrid search begins."""

    type: Literal["hybrid_search_start"] = "hybrid_search_start"
    node: Literal["retriever"] = "retriever"
    query: str
    alpha: AlphaWeight  # Validated to [0.0, 1.0]
    fetch_k: Annotated[int, Field(gt=0, description="Number of documents to fetch (must be > 0)")]


class SearchCandidate(BaseModel):
  """A single search candidate before reranking."""

  source: str
  snippet: str
  full_content: Optional[str] = None
  vector_score: Optional[float] = None
  text_score: Optional[float] = None
  rrf_score: Optional[float] = None
  url: Optional[str] = None


class HybridSearchResultEvent(BaseEvent):
    """Emitted when hybrid search completes with candidates."""

    type: Literal["hybrid_search_result"] = "hybrid_search_result"
    node: Literal["tools"] = "tools"
    candidate_count: int
    candidates: List[SearchCandidate]


# ============================================================================
# RERANKER EVENTS
# ============================================================================


class RerankerStartEvent(BaseEvent):
    """Emitted when reranking begins."""

    type: Literal["reranker_start"] = "reranker_start"
    node: Literal["retriever"] = "retriever"
    model: str
    candidate_count: int


class RerankedDocument(BaseModel):
  """A document after reranking with its new score and rank."""

  source: str
  score: ConfidenceScore  # Cross-encoder score (0.0-1.0), validated
  rank: Annotated[int, Field(gt=0, description="New rank after reranking (1-indexed, must be > 0)")]
  original_rank: Annotated[int, Field(gt=0, description="Rank before reranking (1-indexed, must be > 0)")]
  snippet: str
  rank_change: int = 0  # How much the rank changed (computed: rank - original_rank)
  url: Optional[str] = None

  @field_validator("rank_change", mode="after")
  @classmethod
  def validate_rank_change(cls, rank_change: int, info) -> int:
    """Ensure rank_change is consistent with rank and original_rank."""
    rank = info.data.get("rank")
    original_rank = info.data.get("original_rank")
    if rank is not None and original_rank is not None:
      expected = rank - original_rank
      if rank_change != expected:
        raise ValueError(f"rank_change={rank_change} but rank - original_rank = {expected}")
    return rank_change


class RerankerResultEvent(BaseEvent):
    """Emitted when reranking completes with scored documents."""

    type: Literal["reranker_result"] = "reranker_result"
    node: Literal["tools"] = "tools"
    results: List[RerankedDocument]
    reranking_changed_order: bool = False


# ============================================================================
# SEARCH PROGRESS EVENTS
# ============================================================================


class SearchProgressEvent(BaseEvent):
    """Emitted during search to show real-time progress."""

    type: Literal["search_progress"] = "search_progress"
    node: Literal["retriever"] = "retriever"
    stage: Literal["embedding", "vector_search", "text_search", "fusion"] = "embedding"
    message: str  # e.g., "Embedding query...", "Searching vector index..."


class RerankerProgressEvent(BaseEvent):
    """Emitted during reranking to show real-time progress."""

    type: Literal["reranker_progress"] = "reranker_progress"
    node: Literal["retriever"] = "retriever"
    stage: Literal["scoring", "ranking"] = "scoring"
    progress: ProgressPercent = 0.0  # 0.0-1.0, validated
    message: str  # e.g., "Scoring document 20/40..."


# ============================================================================
# DOCUMENT GRADING EVENTS
# ============================================================================


class DocumentGradingStartEvent(BaseEvent):
    """Emitted when document grading begins."""

    type: Literal["document_grading_start"] = "document_grading_start"
    node: Literal["document_grader"] = "document_grader"
    document_count: int


class DocumentGradeEvent(BaseEvent):
    """Emitted for each document that is graded."""

    type: Literal["document_grade"] = "document_grade"
    node: Literal["document_grader"] = "document_grader"
    source: str
    relevant: bool
    score: ConfidenceScore  # 0.0-1.0, validated
    reasoning: str


class DocumentGradingSummaryEvent(BaseEvent):
    """Emitted when all document grading is complete."""

    type: Literal["document_grading_summary"] = "document_grading_summary"
    node: Literal["document_grader"] = "document_grader"
    grade: Literal["pass", "fail"]  # Only valid grades
    relevant_count: Annotated[int, Field(ge=0, description="Count of relevant documents")]
    total_count: Annotated[int, Field(gt=0, description="Total documents graded (must be > 0)")]
    average_score: ConfidenceScore  # 0.0-1.0, validated
    reasoning: str


# ============================================================================
# QUERY TRANSFORMATION EVENTS
# ============================================================================


class QueryTransformationEvent(BaseEvent):
    """Emitted when query is transformed for retry."""

    type: Literal["query_transformation"] = "query_transformation"
    node: Literal["query_transformer"] = "query_transformer"
    original_query: str
    transformed_query: str
    iteration: int
    max_iterations: int
    reasons: List[str]  # Why documents failed


# ============================================================================
# LLM RESPONSE EVENTS
# ============================================================================


class LLMReasoningStartEvent(BaseEvent):
    """Emitted when LLM starts generating reasoning."""

    type: Literal["llm_reasoning_start"] = "llm_reasoning_start"
    node: Literal["agent"] = "agent"


class LLMReasoningChunkEvent(BaseEvent):
    """Emitted for each chunk of LLM reasoning (streamed)."""

    type: Literal["llm_reasoning_chunk"] = "llm_reasoning_chunk"
    node: Literal["agent"] = "agent"
    content: str
    is_complete: bool = False


class LLMResponseStartEvent(BaseEvent):
    """Emitted when LLM starts generating response."""

    type: Literal["llm_response_start"] = "llm_response_start"
    node: Literal["agent"] = "agent"


class LLMResponseChunkEvent(BaseEvent):
    """Emitted for each chunk of LLM response (streamed)."""

    type: Literal["llm_response_chunk"] = "llm_response_chunk"
    node: Literal["agent"] = "agent"
    content: str
    is_complete: bool = False


class ToolCallEvent(BaseEvent):
    """Emitted when agent decides to call a tool."""

    type: Literal["tool_call"] = "tool_call"
    node: Literal["agent"] = "agent"
    tool_name: str
    tool_args: Dict[str, Any]


# ============================================================================
# RESPONSE GRADING EVENTS
# ============================================================================


class ResponseGradingEvent(BaseEvent):
    """Emitted when response quality is evaluated."""

    type: Literal["response_grading"] = "response_grading"
    node: Literal["response_grader"] = "response_grader"
    grade: str  # "pass" or "fail"
    score: float  # 0.0-1.0
    score_source: Optional[str] = None  # "reranker", "honest_ack", or "llm"
    reasoning: str
    retry_count: int
    max_retries: int


# ============================================================================
# RESPONSE IMPROVEMENT EVENTS
# ============================================================================


class ResponseImprovementEvent(BaseEvent):
    """Emitted when response improvement is triggered."""

    type: Literal["response_improvement"] = "response_improvement"
    node: Literal["response_improver"] = "response_improver"
    feedback: str
    retry_count: int


# ============================================================================
# COMPLETION EVENTS
# ============================================================================


class AgentCompleteEvent(BaseEvent):
    """Emitted when agent execution completes successfully."""

    type: Literal["agent_complete"] = "agent_complete"
    thread_id: str
    total_duration_ms: float
    final_response: str
    iterations: int = 0  # Number of retrieval iterations
    response_retries: int = 0  # Number of response retries
    documents_used: int = 0
    citations: Optional[List[Dict[str, str]]] = None
    title: Optional[str] = None  # Generated conversation title


class AgentErrorEvent(BaseEvent):
    """Emitted when agent execution fails."""

    type: Literal["agent_error"] = "agent_error"
    error: str
    node: Optional[str] = None
    recoverable: bool = False


# ============================================================================
# TOKEN BUDGET EVENTS
# ============================================================================


class TokenBudgetEvent(BaseEvent):
    """Emitted when token usage is tracked against budget."""

    type: Literal["token_budget"] = "token_budget"
    total_tokens_used: int
    token_budget: int
    budget_exceeded: bool
    warning_threshold_hit: bool


# ============================================================================
# CACHE HIT EVENTS
# ============================================================================


class CacheHitEvent(BaseEvent):
    """Emitted when a cache hit occurs."""

    type: Literal["cache_hit"] = "cache_hit"
    node: Literal["query_evaluator"] = "query_evaluator"
    query: str
    cached_result: Dict[str, Any]  # alpha + query_analysis


# ============================================================================
# CONFIDENCE SCORE EVENTS
# ============================================================================


class ConfidenceScoreEvent(BaseEvent):
    """Emitted when confidence scoring is performed."""

    type: Literal["confidence_score"] = "confidence_score"
    node: str  # response_grader, document_grader, etc.
    score: float  # 0.0-1.0
    confidence: float  # 0.0-1.0
    early_stop_triggered: bool


# ============================================================================
# METRICS EVENT
# ============================================================================


class MetricsEvent(BaseEvent):
    """Emitted with timing and performance metrics."""

    type: Literal["metrics"] = "metrics"
    query_evaluation_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    reranking_ms: Optional[float] = None
    document_grading_ms: Optional[float] = None
    llm_generation_ms: Optional[float] = None
    response_grading_ms: Optional[float] = None
    total_ms: float


# ============================================================================
# LINK VERIFICATION EVENTS
# ============================================================================


class LinkVerificationEvent(BaseEvent):
    """Emitted when citation links are verified."""

    type: Literal["link_verification"] = "link_verification"
    node: Literal["agent"] = "agent"
    total_links_checked: int
    valid_links: int
    broken_links: int
    broken_link_sources: List[str] = []  # Sources with broken links
    cache_hits: int = 0


class DocumentReplacementEvent(BaseEvent):
    """Emitted when documents with broken links are replaced."""

    type: Literal["document_replacement"] = "document_replacement"
    node: Literal["agent"] = "agent"
    replacements_made: int
    replacement_details: List[Dict[str, str]] = []  # {old_source, new_source, reason}
    documents_after_replacement: int


# ============================================================================
# CONFIG BUILDER EVENTS
# ============================================================================


class ConfigBuilderStartEvent(BaseEvent):
    """Emitted when config builder starts processing a request."""

    type: Literal["config_builder_start"] = "config_builder_start"
    node: Literal["config_resolver"] = "config_resolver"
    user_request: str


class ResolvedComponent(BaseModel):
    """Detail for a single resolved component."""
    name: str
    component_type: str  # connector, stage, indexer
    resolved: bool  # True = exact spec found, False = search fallback
    class_name: Optional[str] = None  # Full Java class name if resolved
    description: Optional[str] = None  # Component description if resolved


class ComponentSpecRetrievalEvent(BaseEvent):
    """Emitted when component specs are resolved for config building."""

    type: Literal["component_spec_retrieval"] = "component_spec_retrieval"
    node: Literal["config_resolver"] = "config_resolver"
    pipeline_description: str = ""
    components_requested: List[str]
    components_found: List[str]
    components_not_found: List[str] = []
    component_details: List[ResolvedComponent] = []


class ConfigGeneratedEvent(BaseEvent):
    """Emitted when a config has been generated."""

    type: Literal["config_generated"] = "config_generated"
    node: Literal["config_generator"] = "config_generator"
    config_preview: str
    component_count: int
    validation_notes: List[str] = []


class ConfigValidationEvent(BaseEvent):
    """Emitted when config validation completes."""

    type: Literal["config_validation"] = "config_validation"
    node: Literal["config_validator"] = "config_validator"
    valid: bool
    attempt: int
    error_count: int = 0
    errors: Dict[str, List[str]] = {}
    will_retry: bool = False


# ============================================================================
# DOCUMENTATION WRITER EVENTS
# ============================================================================


class DocOutlineEvent(BaseEvent):
    """Emitted when documentation outline is created."""

    type: Literal["doc_outline"] = "doc_outline"
    node: Literal["doc_planner"] = "doc_planner"
    sections: List[str]
    total_components: int


class DocSectionProgressEvent(BaseEvent):
    """Emitted as content is gathered for each documentation section."""

    type: Literal["doc_section_progress"] = "doc_section_progress"
    node: Literal["doc_gatherer"] = "doc_gatherer"
    section_title: str
    sections_complete: int
    sections_total: int
    components_gathered: int


class DocCompleteEvent(BaseEvent):
    """Emitted when documentation generation is complete."""

    type: Literal["doc_complete"] = "doc_complete"
    node: Literal["doc_synthesizer"] = "doc_synthesizer"
    total_sections: int
    total_components_documented: int
    document_length_chars: int


# ============================================================================
# CONTENT TYPE CLASSIFICATION EVENTS
# ============================================================================


class ContentTypeClassificationEvent(BaseEvent):
    """Emitted when content type is classified for documentation request."""

    type: Literal["content_type_classification"] = "content_type_classification"
    node: Literal["content_type_classifier"] = "content_type_classifier"
    content_type: str  # social_post, blog_post, technical_article, tutorial, comprehensive_docs
    confidence: float  # 0.0-1.0
    target_length: int  # Target word count
    tone: str  # engaging, narrative, technical, instructional, reference
    retrieval_depth: int  # Number of retrieval passes (1-5)
    temperature: float  # LLM temperature for generation


class SocialPostProgressEvent(BaseEvent):
    """Emitted during social post generation."""

    type: Literal["social_post_progress"] = "social_post_progress"
    node: Literal["social_content_generator"] = "social_content_generator"
    stage: Literal["retrieval", "generation"]
    message: str


class BlogPostProgressEvent(BaseEvent):
    """Emitted during blog post generation."""

    type: Literal["blog_post_progress"] = "blog_post_progress"
    node: Literal["blog_content_generator"] = "blog_content_generator"
    stage: Literal["outline", "retrieval_pass_1", "retrieval_pass_2", "generation"]
    message: str


class ArticleProgressEvent(BaseEvent):
    """Emitted during technical article generation."""

    type: Literal["article_progress"] = "article_progress"
    node: Literal["article_content_generator"] = "article_content_generator"
    stage: Literal["outline", "retrieval_pass_1", "retrieval_pass_2", "retrieval_pass_3", "generation"]
    message: str


class TutorialProgressEvent(BaseEvent):
    """Emitted during tutorial generation."""

    type: Literal["tutorial_progress"] = "tutorial_progress"
    node: Literal["tutorial_generator"] = "tutorial_generator"
    stage: Literal["outline", "concept_retrieval", "example_retrieval", "generation"]
    message: str


class ContentCompleteEvent(BaseEvent):
    """Emitted when content generation is complete."""

    type: Literal["content_complete"] = "content_complete"
    node: str  # Node name that generated the content
    content_type: str  # Type of content generated
    content_length_words: int
    content_length_chars: int


# ============================================================================
# CLARIFICATION EVENTS
# ============================================================================


class ClarificationRequestedEvent(BaseEvent):
    """Emitted when classifier detects vague query requiring user clarification.

    Clarification types:
    - "format": Query doesn't specify content format (e.g., "write about X")
    - "topic": Query lacks explicit topic (e.g., "write a blog post")
    - "content_type": DEPRECATED (was: LLM low confidence - removed in favor of query vagueness detection)
    """

    type: Literal["clarification_requested"] = "clarification_requested"
    node: Literal["content_type_classifier"] = "content_type_classifier"
    clarification_type: str  # "format" | "topic" | "content_type" (deprecated)
    reason: str  # e.g., "Query doesn't specify content format"
    candidates: List[Dict[str, Any]]  # [{"type": "blog_post", "confidence": 0.0, "description": "..."}, ...]
    threshold: float  # Always 1.0 for vagueness-based clarification (not confidence-based)
    original_query: str  # User's original query


class ClarificationResolvedEvent(BaseEvent):
    """Emitted when user provides clarification and it's resolved."""

    type: Literal["clarification_resolved"] = "clarification_resolved"
    node: Literal["format_clarification_resolver"] = "format_clarification_resolver"
    clarification_type: str  # "format" | "topic"
    original_classification: str  # Classifier's original top choice
    user_selected: str  # What user selected
    confidence_before: float  # Confidence before clarification (0.0 for vagueness-based)
    confidence_after: float  # Always 1.0 (user-confirmed)
    user_response: str  # Raw user response ("1", "2", "blog post", etc.)


# ============================================================================
# UNION TYPE FOR ALL EVENTS
# ============================================================================

AgentEvent = (
    ConnectionEstablished
    | ConnectionError
    | ConversationContextEvent
    | NodeStartEvent
    | NodeEndEvent
    | QueryEvaluationEvent
    | IntentClassificationEvent
    | SummaryEvent
    | HybridSearchStartEvent
    | HybridSearchResultEvent
    | SearchProgressEvent
    | RerankerProgressEvent
    | RerankerStartEvent
    | RerankerResultEvent
    | DocumentGradingStartEvent
    | DocumentGradeEvent
    | DocumentGradingSummaryEvent
    | QueryTransformationEvent
    | QueryExpansionEvent
    | AlphaRefinementEvent
    | LLMReasoningStartEvent
    | LLMReasoningChunkEvent
    | LLMResponseStartEvent
    | LLMResponseChunkEvent
    | ToolCallEvent
    | ResponseGradingEvent
    | ResponseImprovementEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | TokenBudgetEvent
    | CacheHitEvent
    | ConfidenceScoreEvent
    | MetricsEvent
    | LinkVerificationEvent
    | DocumentReplacementEvent
    | ConfigBuilderStartEvent
    | ComponentSpecRetrievalEvent
    | ConfigGeneratedEvent
    | DocOutlineEvent
    | ContentTypeClassificationEvent
    | SocialPostProgressEvent
    | BlogPostProgressEvent
    | ArticleProgressEvent
    | TutorialProgressEvent
    | ContentCompleteEvent
    | ClarificationRequestedEvent
    | ClarificationResolvedEvent
    | DocSectionProgressEvent
    | DocCompleteEvent
)
