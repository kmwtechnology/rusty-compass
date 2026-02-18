/**
 * TypeScript types for WebSocket events from the agent API.
 * These mirror the Pydantic models in api/schemas/events.py
 */

// Base event interface
export interface BaseEvent {
  type: string
  timestamp: string
  node?: string
}

// Connection events
export interface ConnectionEstablished extends BaseEvent {
  type: 'connection_established'
  thread_id: string
  existing_messages: number
}

export interface ConnectionError extends BaseEvent {
  type: 'connection_error'
  error: string
}

// Conversation context events
export interface ConversationContextEvent extends BaseEvent {
  type: 'conversation_context'
  previous_message_count: number
  is_new_conversation: boolean
  summary?: string
}

// Node lifecycle events
export interface NodeStartEvent extends BaseEvent {
  type: 'node_start'
  node: string
  input_summary?: string
}

export interface NodeEndEvent extends BaseEvent {
  type: 'node_end'
  node: string
  duration_ms: number
  output_summary?: string
}

// Query evaluator events
export interface QueryEvaluationEvent extends BaseEvent {
  type: 'query_evaluation'
  node: 'query_evaluator'
  query: string
  alpha: number
  query_analysis: string
  search_strategy: 'lexical-heavy' | 'balanced' | 'semantic-heavy'
}

export interface IntentClassificationEvent extends BaseEvent {
  type: 'intent_classification'
  node: 'intent_classifier'
  intent: string
  user_query: string
  reasoning: string
  confidence?: number  // 0.0-1.0 confidence score
}

export interface QueryExpansionEvent extends BaseEvent {
  type: 'query_expansion'
  node: 'retriever'
  original_query: string
  expanded_query: string
  expansion_reason: string
}

export interface AlphaRefinementEvent extends BaseEvent {
  type: 'alpha_refinement'
  node: 'alpha_refiner'
  triggered: boolean
  original_alpha: number
  new_alpha?: number
  max_score: number
  threshold: number
  reason: string
}

export interface SummaryEvent extends BaseEvent {
  type: 'summary_generated'
  node: 'summary'
  summary_text?: string
  message_count: number
}

// Hybrid search events
export interface SearchCandidate {
  source: string
  snippet: string
  full_content?: string
  vector_score?: number
  text_score?: number
  rrf_score?: number
  url?: string
}

export interface HybridSearchStartEvent extends BaseEvent {
  type: 'hybrid_search_start'
  node: 'retriever'
  query: string
  alpha: number
  fetch_k: number
}

export interface HybridSearchResultEvent extends BaseEvent {
  type: 'hybrid_search_result'
  node: 'retriever'
  candidate_count: number
  candidates: SearchCandidate[]
}

// Reranker events
export interface RerankerStartEvent extends BaseEvent {
  type: 'reranker_start'
  node: 'retriever'
  model: string
  candidate_count: number
}

export interface RerankedDocument {
  source: string
  score: number
  rank: number
  original_rank: number
  snippet: string
  rank_change: number
  url?: string
  // Optional component scores (may be included from hybrid search)
  vector_score?: number
  text_score?: number
  rrf_score?: number
  page_content?: string
}

export interface RerankerResultEvent extends BaseEvent {
  type: 'reranker_result'
  node: 'retriever'
  results: RerankedDocument[]
  reranking_changed_order: boolean
}

// Search progress events
export interface SearchProgressEvent extends BaseEvent {
  type: 'search_progress'
  node: 'retriever'
  stage: 'embedding' | 'vector_search' | 'text_search' | 'fusion'
  message: string
}

export interface RerankerProgressEvent extends BaseEvent {
  type: 'reranker_progress'
  node: 'retriever'
  stage: 'scoring' | 'ranking'
  progress: number  // 0.0-1.0
  message: string
}

// Document grading events
export interface DocumentGradingStartEvent extends BaseEvent {
  type: 'document_grading_start'
  node: 'document_grader'
  document_count: number
}

export interface DocumentGradeEvent extends BaseEvent {
  type: 'document_grade'
  node: 'document_grader'
  source: string
  relevant: boolean
  score: number
  reasoning: string
}

export interface DocumentGradingSummaryEvent extends BaseEvent {
  type: 'document_grading_summary'
  node: 'document_grader'
  grade: 'pass' | 'fail'
  relevant_count: number
  total_count: number
  average_score: number
  reasoning: string
}

// Query transformation events
export interface QueryTransformationEvent extends BaseEvent {
  type: 'query_transformation'
  node: 'query_transformer'
  original_query: string
  transformed_query: string
  iteration: number
  max_iterations: number
  reasons: string[]
}

// LLM response events
export interface LLMReasoningStartEvent extends BaseEvent {
  type: 'llm_reasoning_start'
  node: 'agent'
}

export interface LLMReasoningChunkEvent extends BaseEvent {
  type: 'llm_reasoning_chunk'
  node: 'agent'
  content: string
  is_complete: boolean
}

export interface LLMResponseStartEvent extends BaseEvent {
  type: 'llm_response_start'
  node: 'agent'
}

export interface LLMResponseChunkEvent extends BaseEvent {
  type: 'llm_response_chunk'
  node: 'agent'
  content: string
  is_complete: boolean
}

export interface ToolCallEvent extends BaseEvent {
  type: 'tool_call'
  node: 'agent'
  tool_name: string
  tool_args: Record<string, unknown>
}

// Response grading events
export interface ResponseGradingEvent extends BaseEvent {
  type: 'response_grading'
  node: 'response_grader'
  grade: 'pass' | 'fail'
  score: number
  score_source?: 'reranker' | 'honest_ack' | 'llm'  // Source of the score
  reasoning: string
  retry_count: number
  max_retries: number
}

// Response improvement events
export interface ResponseImprovementEvent extends BaseEvent {
  type: 'response_improvement'
  node: 'response_improver'
  feedback: string
  retry_count: number
}

// Completion events
export interface AgentCompleteEvent extends BaseEvent {
  type: 'agent_complete'
  thread_id: string
  total_duration_ms: number
  final_response: string
  iterations: number
  response_retries: number
  documents_used: number
  title?: string
  citations?: { label: string; url: string }[]
}

export interface AgentErrorEvent extends BaseEvent {
  type: 'agent_error'
  error: string
  node?: string
  recoverable: boolean
}

// Token budget events
export interface TokenBudgetEvent extends BaseEvent {
  type: 'token_budget'
  total_tokens_used: number
  token_budget: number
  budget_exceeded: boolean
  warning_threshold_hit: boolean
}

// Cache hit events
export interface CacheHitEvent extends BaseEvent {
  type: 'cache_hit'
  node: 'query_evaluator'
  query: string
  cached_result: Record<string, unknown>
}

// Confidence score events
export interface ConfidenceScoreEvent extends BaseEvent {
  type: 'confidence_score'
  node: string
  score: number
  confidence: number
  early_stop_triggered: boolean
}

// Link verification events
export interface LinkVerificationEvent extends BaseEvent {
  type: 'link_verification'
  node: 'agent'
  total_links_checked: number
  valid_links: number
  broken_links: number
  broken_link_sources: string[]
  cache_hits: number
}

export interface DocumentReplacementEvent extends BaseEvent {
  type: 'document_replacement'
  node: 'agent'
  replacements_made: number
  replacement_details: Array<{ old_source: string; new_source: string; reason: string }>
  documents_after_replacement: number
}

// Config builder events
export interface ConfigBuilderStartEvent extends BaseEvent {
  type: 'config_builder_start'
  node: 'config_resolver'
  user_request: string
}

export interface ResolvedComponentDetail {
  name: string
  component_type: string
  resolved: boolean
  class_name?: string
  description?: string
}

export interface ComponentSpecRetrievalEvent extends BaseEvent {
  type: 'component_spec_retrieval'
  node: 'config_resolver'
  pipeline_description?: string
  components_requested: string[]
  components_found: string[]
  components_not_found: string[]
  component_details?: ResolvedComponentDetail[]
}

export interface ConfigGeneratedEvent extends BaseEvent {
  type: 'config_generated'
  node: 'config_generator'
  config_preview: string
  component_count: number
  validation_notes: string[]
}

// Documentation writer events
export interface DocOutlineEvent extends BaseEvent {
  type: 'doc_outline'
  node: 'doc_planner'
  sections: string[]
  total_components: number
}

export interface DocSectionProgressEvent extends BaseEvent {
  type: 'doc_section_progress'
  node: 'doc_gatherer'
  section_title: string
  sections_complete: number
  sections_total: number
  components_gathered: number
}

export interface DocCompleteEvent extends BaseEvent {
  type: 'doc_complete'
  node: 'doc_synthesizer'
  total_sections: number
  total_components_documented: number
  document_length_chars: number
}

// Content type classification events
export interface ContentTypeClassificationEvent extends BaseEvent {
  type: 'content_type_classification'
  node: 'content_type_classifier'
  content_type: 'social_post' | 'blog_post' | 'technical_article' | 'tutorial' | 'comprehensive_docs'
  confidence: number
  target_length: number
  tone: string
  retrieval_depth: number
  temperature: number
}

export interface SocialPostProgressEvent extends BaseEvent {
  type: 'social_post_progress'
  node: 'social_content_generator'
  stage: 'retrieval' | 'generation'
  message: string
}

export interface BlogPostProgressEvent extends BaseEvent {
  type: 'blog_post_progress'
  node: 'blog_content_generator'
  stage: 'outline' | 'retrieval_pass_1' | 'retrieval_pass_2' | 'generation'
  message: string
}

export interface ArticleProgressEvent extends BaseEvent {
  type: 'article_progress'
  node: 'article_content_generator'
  stage: 'outline' | 'retrieval_pass_1' | 'retrieval_pass_2' | 'retrieval_pass_3' | 'generation'
  message: string
}

export interface TutorialProgressEvent extends BaseEvent {
  type: 'tutorial_progress'
  node: 'tutorial_generator'
  stage: 'outline' | 'concept_retrieval' | 'example_retrieval' | 'generation'
  message: string
}

export interface ContentCompleteEvent extends BaseEvent {
  type: 'content_complete'
  node: string
  content_type: string
  content_length_words: number
  content_length_chars: number
}

// Clarification events
export interface ClarificationRequestedEvent extends BaseEvent {
  type: 'clarification_requested'
  node: 'content_type_classifier'
  clarification_type: string
  reason: string
  candidates: Array<{
    type: string
    confidence: number
    description: string
  }>
  threshold: number
  original_query: string
}

export interface ClarificationResolvedEvent extends BaseEvent {
  type: 'clarification_resolved'
  node: 'content_type_clarification_resolver'
  clarification_type: string
  original_classification: string
  user_selected: string
  confidence_before: number
  confidence_after: number
  user_response: string
}

// Union type of all events
export type AgentEvent =
  | ConnectionEstablished
  | ConnectionError
  | ConversationContextEvent
  | NodeStartEvent
  | NodeEndEvent
  | QueryEvaluationEvent
  | IntentClassificationEvent
  | QueryExpansionEvent
  | AlphaRefinementEvent
  | SummaryEvent
  | HybridSearchStartEvent
  | HybridSearchResultEvent
  | RerankerStartEvent
  | RerankerResultEvent
  | SearchProgressEvent
  | RerankerProgressEvent
  | DocumentGradingStartEvent
  | DocumentGradeEvent
  | DocumentGradingSummaryEvent
  | QueryTransformationEvent
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
  | LinkVerificationEvent
  | DocumentReplacementEvent
  | ConfigBuilderStartEvent
  | ComponentSpecRetrievalEvent
  | ConfigGeneratedEvent
  | DocOutlineEvent
  | DocSectionProgressEvent
  | DocCompleteEvent
  | ContentTypeClassificationEvent
  | SocialPostProgressEvent
  | BlogPostProgressEvent
  | ArticleProgressEvent
  | TutorialProgressEvent
  | ContentCompleteEvent
  | ClarificationRequestedEvent
  | ClarificationResolvedEvent

// Helper type guards
export function isQueryEvaluation(event: AgentEvent): event is QueryEvaluationEvent {
  return event.type === 'query_evaluation'
}

export function isDocumentGradingSummary(event: AgentEvent): event is DocumentGradingSummaryEvent {
  return event.type === 'document_grading_summary'
}

export function isResponseGrading(event: AgentEvent): event is ResponseGradingEvent {
  return event.type === 'response_grading'
}

export function isAgentComplete(event: AgentEvent): event is AgentCompleteEvent {
  return event.type === 'agent_complete'
}

export function isAgentError(event: AgentEvent): event is AgentErrorEvent {
  return event.type === 'agent_error'
}

export function isQueryExpansion(event: AgentEvent): event is QueryExpansionEvent {
  return event.type === 'query_expansion'
}

export function isAlphaRefinement(event: AgentEvent): event is AlphaRefinementEvent {
  return event.type === 'alpha_refinement'
}

export function isIntentClassification(event: AgentEvent): event is IntentClassificationEvent {
  return event.type === 'intent_classification'
}

// Node names for routing
export type NodeName =
  | 'query_evaluator'
  | 'retriever'
  | 'alpha_refiner'
  | 'agent'
  | 'intent_classifier'
  | 'summary'
  | 'config_resolver'
  | 'config_generator'
  | 'config_response'
  | 'content_type_classifier'
  | 'social_content_generator'
  | 'blog_content_generator'
  | 'article_content_generator'
  | 'tutorial_generator'
  | 'doc_planner'
  | 'doc_gatherer'
  | 'doc_synthesizer'

// Node status for UI
export type NodeStatus = 'idle' | 'running' | 'complete' | 'error'

// Step representation for the observability panel
export interface ObservabilityStep {
  id: string
  node: NodeName
  status: NodeStatus
  startTime: Date
  endTime?: Date
  durationMs?: number
  events: AgentEvent[]
  summary?: string
}
