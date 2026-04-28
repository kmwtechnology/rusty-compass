"""
Observable Agent Service - Wrapper for LucilleAgent with event emission.

This service wraps the existing LucilleAgent and emits WebSocket events
during execution, providing full observability into the agent's workflow.
"""

import warnings

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from langchain_core.messages import AIMessage, HumanMessage

# Get logger for this module
logger = logging.getLogger(__name__)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import LucilleAgent
from config import (
    ENABLE_RERANKING,
    RERANKER_MODEL,
    RETRIEVER_FETCH_K,
)

from api.schemas.events import (
    BaseEvent,
    ConversationContextEvent,
    NodeStartEvent,
    NodeEndEvent,
    QueryEvaluationEvent,
    HybridSearchStartEvent,
    HybridSearchResultEvent,
    SearchCandidate,
    RerankerStartEvent,
    RerankerResultEvent,
    RerankedDocument,
    LLMReasoningStartEvent,
    LLMReasoningChunkEvent,
    LLMResponseStartEvent,
    LLMResponseChunkEvent,
    ToolCallEvent,
    IntentClassificationEvent,
    SummaryEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    MetricsEvent,
    QueryExpansionEvent,
    AlphaRefinementEvent,
    ConfigBuilderStartEvent,
    ComponentSpecRetrievalEvent,
    ConfigGeneratedEvent,
    DocOutlineEvent,
    DocSectionProgressEvent,
    DocCompleteEvent,
)


# Type alias for emit callback
EmitCallback = Callable[[BaseEvent], Coroutine[Any, Any, None]]


class ObservableAgentService:
    """
    Observable wrapper for LucilleAgent that emits events during execution.

    This service provides the same functionality as LucilleAgent but emits
    structured events at each step, enabling real-time observability in the UI.
    """

    def __init__(self):
        """Initialize the observable agent service (lazy loading)."""
        self._agent: Optional[LucilleAgent] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def ensure_initialized(self):
        """Initialize the agent if not already done."""
        async with self._lock:
            if not self._initialized:
                await self._initialize_agent()
                await self._open_async_pool()
                self._initialized = True

    async def _initialize_agent(self):
        """Initialize the underlying LucilleAgent."""
        # Run synchronous initialization in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_init_agent)

    def _sync_init_agent(self):
        """Synchronous agent initialization."""
        self._agent = LucilleAgent()
        # Skip prerequisite verification in API mode
        # (health endpoint handles this)
        self._agent.initialize_components()
        self._agent.create_agent_graph()

    async def _open_async_pool(self):
        """Open the async pool for astream_events support."""
        if self._agent:
            await self._agent.ensure_async_pool_open()

    async def _load_conversation_context(self, thread_id: str) -> int:
        """
        Load previous message count from checkpoint.

        Args:
            thread_id: The conversation thread ID

        Returns:
            Number of previous human/AI messages in the conversation
        """
        try:
            pool = self._agent.async_pool
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("""
                        SELECT blob, type FROM checkpoint_blobs
                        WHERE thread_id = %s AND channel = 'messages'
                        ORDER BY version DESC LIMIT 1
                    """, (thread_id,))
                    blob_row = await cur.fetchone()
                    if blob_row and blob_row[0]:
                        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
                        serializer = JsonPlusSerializer()
                        messages = serializer.loads_typed((blob_row[1], blob_row[0]))
                        # Count human and AI messages
                        return len([m for m in messages if hasattr(m, 'type') and m.type in ('human', 'ai')])
            return 0
        except Exception:
            return 0

    async def process_message(
        self,
        message: str,
        thread_id: str,
        emit: EmitCallback,
    ) -> Optional[str]:
        """
        Process a user message through the agent with observability.

        Args:
            message: The user's message
            thread_id: Conversation thread ID for persistence
            emit: Callback to emit events to the WebSocket

        Returns:
            The agent's final response text, or None if failed.
        """
        start_time = time.time()
        metrics: Dict[str, float] = {}

        try:
            # Set thread for conversation persistence
            self._agent.set_thread_id(thread_id)

            # Set emit callback for intermediate events from retriever_node
            # Also store the current event loop so retriever_node can use it
            import asyncio
            self._agent.emit_callback = emit
            try:
                self._agent.event_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass  # No running loop, will fallback to queueing

            # Load and emit conversation context
            previous_count = await self._load_conversation_context(thread_id)
            is_new = previous_count == 0
            await emit(ConversationContextEvent(
                previous_message_count=previous_count,
                is_new_conversation=is_new,
                summary="New conversation" if is_new else f"Loaded {previous_count} previous messages",
            ))

            # Build initial state
            # Reset per-query state (alpha, alpha_adjusted) while preserving conversation history via checkpoint
            from config import DEFAULT_ALPHA
            initial_state = {
                "messages": [HumanMessage(content=message)],
                "alpha": DEFAULT_ALPHA,
                "query_analysis": "",
                "alpha_adjusted": False,  # Reset for each new message
            }

            config = {"configurable": {"thread_id": thread_id}}

            # Track metrics timing
            node_start_times: Dict[str, float] = {}
            final_response: Optional[str] = None
            documents_used = 0
            citations: List[Dict[str, str]] = []

            # Stream through the graph
            async for event in self._astream_graph(initial_state, config, emit, node_start_times, metrics):
                # Extract final response from agent completions
                if isinstance(event, dict):
                    if "messages" in event:
                        for msg in event.get("messages", []):
                            if isinstance(msg, AIMessage) and msg.content:
                                if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                                    final_response = msg.content
                                    logger.debug(f"Extracted final_response: {len(final_response)} chars")

                    if "retrieved_documents" in event:
                        documents_used = len(event["retrieved_documents"])
                    if "citations" in event and isinstance(event["citations"], list):
                        citations = event["citations"]

            logger.info(f"Graph execution completed. Preparing to emit completion event.")

            # Calculate total duration
            total_duration_ms = (time.time() - start_time) * 1000

            # Generate conversation title
            logger.debug(f"Generating title for thread {thread_id}")
            title = await self._generate_title(thread_id, message, final_response)
            logger.debug(f"Title generated: {title}")

            # Emit completion event
            logger.info(f"Emitting AgentCompleteEvent: {len(final_response or '')} chars, {total_duration_ms:.0f}ms")
            await emit(AgentCompleteEvent(
                thread_id=thread_id,
                total_duration_ms=total_duration_ms,
                final_response=final_response or "No response generated",
                iterations=0,
                response_retries=0,
                documents_used=documents_used,
                title=title,
                citations=citations,
            ))
            logger.info("AgentCompleteEvent emitted successfully")

            # Emit metrics
            await emit(MetricsEvent(
                query_evaluation_ms=metrics.get("query_evaluator"),
                retrieval_ms=metrics.get("retriever"),
                document_grading_ms=None,
                llm_generation_ms=metrics.get("agent"),
                response_grading_ms=None,
                total_ms=total_duration_ms,
            ))

            return final_response

        except Exception as e:
            await emit(AgentErrorEvent(
                error=str(e),
                recoverable=False,
            ))
            return None

    async def _emit_queued_events(self, emit: EmitCallback) -> None:
        """
        Process and emit any events queued by the retriever_node.

        The retriever_node runs synchronously and can't directly emit async events,
        so it queues them for later emission.
        """
        while self._agent.event_queue:
            event = self._agent.event_queue.pop(0)
            await emit(event)

    async def _astream_graph(
        self,
        initial_state: Dict[str, Any],
        config: Dict[str, Any],
        emit: EmitCallback,
        node_start_times: Dict[str, float],
        metrics: Dict[str, float],
    ):
        """
        Stream through the agent graph using LangGraph's astream_events v2 API.

        Provides responsive streaming by capturing:
        - on_chain_start/on_chain_end: Node lifecycle events
        - on_chat_model_stream: Individual LLM token chunks
        - on_tool_start/on_tool_end: Tool execution events

        Yields state updates as they occur.
        """
        # Known LangGraph nodes to track (filter out internal chains)
        tracked_nodes = {
            "intent_classifier", "query_evaluator", "summary", "retriever", "alpha_refiner", "agent",
            # Config builder nodes
            "config_resolver", "config_generator", "config_response",
            # Doc writer nodes - content type classification
            "content_type_classifier",
            # Doc writer nodes - content generators
            "social_content_generator", "blog_content_generator",
            "article_content_generator", "tutorial_generator",
            # Doc writer nodes - comprehensive docs
            "doc_planner", "doc_gatherer", "doc_synthesizer",
        }
        current_node: Optional[str] = None
        accumulated_output: Dict[str, Any] = {}
        response_streaming_started = False  # Track if we've started streaming LLM response
        skipped_nodes: Set[str] = set()

        try:
            async for event in self._agent.app.astream_events(
                initial_state,
                config=config,
                version="v2",
            ):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Handle node lifecycle events
                if event_type == "on_chain_start":
                    if event_name == "retriever":
                        input_state = event_data.get("input", {})
                        if input_state.get("intent") == "summary":
                            skipped_nodes.add(event_name)
                            continue

                    if event_name in tracked_nodes:
                        current_node = event_name
                        node_start_times[event_name] = time.time()

                        await emit(NodeStartEvent(
                            node=event_name,
                            input_summary=f"Starting {event_name}",
                        ))

                        # Emit HybridSearchStartEvent immediately when retriever starts
                        if event_name == "retriever":
                            input_state = event_data.get("input", {})
                            query = ""
                            for msg in reversed(input_state.get("messages", [])):
                                if hasattr(msg, "content") and hasattr(msg, "type") and msg.type == "human":
                                    query = msg.content
                                    break

                            await emit(HybridSearchStartEvent(
                                query=query,
                                alpha=input_state.get("alpha", 0.25),
                                fetch_k=RETRIEVER_FETCH_K,
                            ))

                elif event_type == "on_chain_end":
                    if event_name in skipped_nodes:
                        skipped_nodes.remove(event_name)
                        continue

                    if event_name in tracked_nodes:
                        duration_ms = 0.0
                        if event_name in node_start_times:
                            duration_ms = (time.time() - node_start_times[event_name]) * 1000
                            metrics[event_name] = metrics.get(event_name, 0) + duration_ms

                        # Extract output from event
                        output = event_data.get("output", {})
                        if isinstance(output, dict):
                            accumulated_output.update(output)

                            # Emit node-specific events
                            # Pass streaming flag for agent node to avoid duplicate response emission
                            await self._emit_node_events(
                                event_name, output, emit,
                                already_streamed=response_streaming_started if event_name in ("agent", "doc_synthesizer") else False
                            )

                            # Emit any events queued by retriever_node
                            await self._emit_queued_events(emit)

                        # Skip NodeEndEvent for summary node when no summary was generated
                        skip_node_end = (
                            event_name == "summary"
                            and isinstance(output, dict)
                            and output.get("summary_text") is None
                        )

                        if not skip_node_end:
                            await emit(NodeEndEvent(
                                node=event_name,
                                duration_ms=duration_ms,
                                output_summary=self._summarize_output(event_name, output if isinstance(output, dict) else {}),
                            ))

                        # Yield the output for state tracking
                        if isinstance(output, dict) and output:
                            yield output

                # Handle LLM token streaming
                elif event_type == "on_chat_model_stream":
                    # Stream to chat window for agent node and content generator nodes
                    # (query_evaluator outputs JSON which shouldn't be shown to user)
                    streaming_nodes = {
                        "agent",
                        "social_content_generator", "blog_content_generator",
                        "article_content_generator", "tutorial_generator",
                        "doc_synthesizer",
                    }
                    if current_node in streaming_nodes:
                        chunk = event_data.get("chunk")
                        if chunk:
                            # Handle different chunk formats
                            content = None
                            if hasattr(chunk, "content") and chunk.content:
                                content = chunk.content
                            elif isinstance(chunk, dict) and "content" in chunk:
                                content = chunk["content"]

                            if content:
                                # Emit start event on first chunk (enables chat window streaming)
                                if not response_streaming_started:
                                    await emit(LLMResponseStartEvent())
                                    response_streaming_started = True
                                # Emit token chunk directly to WebSocket
                                await emit(LLMResponseChunkEvent(
                                    content=content,
                                    is_complete=False,
                                ))

                # Handle tool events
                elif event_type == "on_tool_start":
                    tool_name = event_name
                    tool_input = event_data.get("input", {})
                    await emit(ToolCallEvent(
                        tool_name=tool_name,
                        tool_args=tool_input if isinstance(tool_input, dict) else {"query": str(tool_input)},
                    ))

        except Exception as e:
            # Log error and re-raise to trigger AgentErrorEvent in process_message
            import traceback
            print(f"Error in astream_events: {e}")
            traceback.print_exc()
            raise

    async def _emit_node_events(
        self,
        node_name: str,
        output: Dict[str, Any],
        emit: EmitCallback,
        already_streamed: bool = False,
    ):
        """Emit detailed events for specific nodes.

        Args:
            already_streamed: If True for agent node, skip re-emitting the full response
                             (it was already streamed token-by-token via on_chat_model_stream)
        """

        if node_name == "intent_classifier":
            await emit(IntentClassificationEvent(
                intent=output.get("intent", "question"),
                user_query=output.get("user_query", ""),
                reasoning=output.get("reasoning", "Heuristic classification"),
                confidence=output.get("confidence") or output.get("intent_confidence"),
            ))
        elif node_name == "query_evaluator":
            await emit(QueryEvaluationEvent(
                query="",  # Original query used as-is (no query rewriting)
                alpha=output.get("alpha", 0.25),
                query_analysis=output.get("query_analysis", ""),
                search_strategy=self._get_search_strategy(output.get("alpha", 0.25)),
            ))

        elif node_name == "summary":
            await emit(SummaryEvent(
                summary_text=output.get("summary_text"),
                message_count=output.get("message_count", 0),
            ))
        elif node_name == "retriever":
            # Emit reranking result events if enabled
            # (hybrid_search_result and reranker_start are now emitted from within retriever_node)
            documents = output.get("retrieved_documents", [])
            if documents and ENABLE_RERANKING:
                # Emit reranker result event with detailed document information
                reranked_docs = self._compute_reranked_documents(documents)
                reranking_changed_order = self._check_if_order_changed(documents, reranked_docs)

                await emit(RerankerResultEvent(
                    results=reranked_docs,
                    reranking_changed_order=reranking_changed_order,
                ))

        elif node_name == "alpha_refiner":
            # Emit alpha refinement event
            from config import ALPHA_REFINEMENT_THRESHOLD, DEFAULT_ALPHA
            triggered = output.get("_needs_retrieval_retry", False)
            await emit(AlphaRefinementEvent(
                triggered=triggered,
                original_alpha=output.get("original_alpha", DEFAULT_ALPHA),
                new_alpha=output.get("alpha") if triggered else None,
                max_score=output.get("max_score", 0.0),
                threshold=ALPHA_REFINEMENT_THRESHOLD,
                reason=output.get("alpha_refinement_reason", ""),
            ))

        elif node_name == "config_resolver":
            # Config builder events are emitted inline from config_resolver_node
            pass

        elif node_name == "config_generator":
            # Config generation events are emitted inline from config_generator_node
            pass

        elif node_name == "config_response":
            # Config response produces final output - emit full content
            messages = output.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage) and msg.content:
                    await emit(LLMResponseStartEvent())
                    await emit(LLMResponseChunkEvent(content=msg.content, is_complete=True))

        elif node_name == "content_type_classifier":
            # Emit clarification messages (hardcoded AIMessages, not LLM-streamed)
            messages = output.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage) and msg.content:
                    await emit(LLMResponseStartEvent())
                    await emit(LLMResponseChunkEvent(content=msg.content, is_complete=True))

        elif node_name in (
            "social_content_generator", "blog_content_generator",
            "article_content_generator", "tutorial_generator",
            "doc_synthesizer",
        ):
            # Content was streamed token-by-token via on_chat_model_stream.
            # Emit completion marker so frontend finalizes the message.
            if already_streamed:
                await emit(LLMResponseChunkEvent(content="", is_complete=True))
            else:
                # Fallback: emit full content if streaming didn't happen
                messages = output.get("messages", [])
                for msg in messages:
                    if isinstance(msg, AIMessage) and msg.content:
                        await emit(LLMResponseStartEvent())
                        await emit(LLMResponseChunkEvent(content=msg.content, is_complete=True))

        elif node_name == "doc_planner":
            # Doc planner events are emitted inline from doc_planner_node
            pass

        elif node_name == "doc_gatherer":
            # Doc gatherer progress events are emitted inline from doc_gatherer_node
            pass

        elif node_name == "agent":
            # Emit LLM events
            messages = output.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage):
                    # Check for reasoning in additional_kwargs
                    reasoning = None
                    if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                        reasoning = msg.additional_kwargs.get("reasoning")

                    # Emit reasoning if present
                    if reasoning:
                        await emit(LLMReasoningStartEvent())
                        await emit(LLMReasoningChunkEvent(
                            content=reasoning,
                            is_complete=True,
                        ))

                    # Check for tool calls
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            await emit(ToolCallEvent(
                                tool_name=tool_call["name"],
                                tool_args=tool_call["args"],
                            ))
                    elif msg.content:
                        # For responses without tool calls, check if content needs parsing
                        # (handles Ollama models that format reasoning as "Reasoning: ... \nAnswer: ...")
                        reasoning_extracted, response_content = self._parse_structured_response(msg.content)

                        # Emit reasoning if extracted from content
                        if reasoning_extracted and not reasoning:
                            await emit(LLMReasoningStartEvent())
                            await emit(LLMReasoningChunkEvent(
                                content=reasoning_extracted,
                                is_complete=True,
                            ))

                        if already_streamed:
                            # Response was already streamed token-by-token to chat window
                            # Just emit completion marker
                            await emit(LLMResponseChunkEvent(
                                content="",
                                is_complete=True,
                            ))
                        else:
                            # Emit full response (fallback for non-streaming models)
                            await emit(LLMResponseStartEvent())
                            await emit(LLMResponseChunkEvent(
                                content=response_content,
                                is_complete=True,
                            ))

    def _parse_structured_response(self, content: str) -> tuple[Optional[str], str]:
        """
        Parse LLM responses that may contain structured reasoning.

        Some models format responses as:
        "Reasoning: <reasoning text>
         Answer: <answer text>"

        Returns:
            A tuple of (reasoning_text, response_text)
            If no structured format is found, returns (None, content)
        """
        if not content:
            return None, content

        # Look for the pattern "Reasoning:" and "Answer:"
        reasoning_pattern = "Reasoning:"
        answer_pattern = "Answer:"

        if reasoning_pattern in content and answer_pattern in content:
            try:
                reasoning_start = content.find(reasoning_pattern) + len(reasoning_pattern)
                reasoning_end = content.find(answer_pattern)

                if reasoning_end > reasoning_start:
                    reasoning_text = content[reasoning_start:reasoning_end].strip()
                    answer_start = reasoning_end + len(answer_pattern)
                    answer_text = content[answer_start:].strip()

                    return reasoning_text, answer_text
            except Exception:
                # If parsing fails, return the original content
                pass

        return None, content

    def _compute_reranked_documents(self, documents: List) -> List:
        """
        Compute RerankedDocument objects from retrieved documents.

        Since the documents in output["retrieved_documents"] are already reranked
        by the retriever_node before reaching this method, we construct RerankedDocument
        objects using their current positions and extract scores from metadata.

        Args:
            documents: List of LangChain Document objects (already reranked)

        Returns:
            List of RerankedDocument objects with ranking information
        """
        reranked_docs = []

        for rank, doc in enumerate(documents, 1):
            source = doc.metadata.get("source", "unknown")
            # Extract reranker score if available, otherwise use 0.0
            score = doc.metadata.get("reranker_score", 0.0)
            # Extract original rank if available, otherwise estimate based on position
            original_rank = doc.metadata.get("original_rank") or rank
            # Calculate rank change (negative = improved/moved up, positive = degraded/moved down)
            rank_change = rank - original_rank

            snippet = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content

            reranked_docs.append(RerankedDocument(
                source=source,
                score=score,
                rank=rank,
                original_rank=original_rank,
                snippet=snippet,
                rank_change=rank_change,
                url=doc.metadata.get("url"),
            ))

        return reranked_docs

    def _check_if_order_changed(self, documents: List, reranked_docs: List) -> bool:
        """
        Determine if reranking changed the document order.

        This is a heuristic check based on whether any document moved from its
        original position. Since we don't have the pre-reranking order directly,
        we check if any document has a non-zero rank_change value.

        Args:
            documents: List of LangChain Document objects (reranked)
            reranked_docs: List of RerankedDocument objects with rank info

        Returns:
            Boolean indicating if any document's rank changed
        """
        return any(doc.rank_change != 0 for doc in reranked_docs)

    def _get_search_strategy(self, alpha: float) -> str:
        """Convert alpha to human-readable search strategy.

        Alpha scale (standard hybrid search convention):
        - 0.0-0.3: Pure lexical (BM25/text-heavy)
        - 0.3-0.7: Balanced hybrid
        - 0.7-1.0: Pure semantic (vector-heavy)
        """
        if alpha < 0.3:
            return "lexical-heavy"
        elif alpha < 0.7:
            return "balanced"
        else:
            return "semantic-heavy"

    def _summarize_input(self, node_name: str, output: Dict[str, Any]) -> str:
        """Generate a brief summary of node input."""
        if node_name == "query_evaluator":
            return "Evaluating query type for optimal search strategy"
        elif node_name == "retriever":
            return "Executing hybrid search + reranking"
        elif node_name == "agent":
            return "Generating response from documents"
        elif node_name == "intent_classifier":
            return "Classifying user intent"
        elif node_name == "summary":
            return "Preparing conversation summary"
        elif node_name == "config_resolver":
            return "Resolving pipeline components"
        elif node_name == "config_generator":
            return "Generating HOCON configuration"
        elif node_name == "config_response":
            return "Formatting config response"
        elif node_name == "doc_planner":
            return "Planning documentation outline"
        elif node_name == "doc_gatherer":
            return "Gathering content for sections"
        elif node_name == "doc_synthesizer":
            return "Synthesizing documentation"
        return ""

    def _summarize_output(self, node_name: str, output: Dict[str, Any]) -> str:
        """Generate a brief summary of node output."""
        if node_name == "query_evaluator":
            return f"alpha={output.get('alpha', 0.25):.2f}"
        elif node_name == "retriever":
            docs = output.get("retrieved_documents", [])
            return f"{len(docs)} documents retrieved"
        elif node_name == "agent":
            messages = output.get("messages", [])
            if messages:
                return "Response generated"
            return ""
        elif node_name == "intent_classifier":
            intent = output.get('intent', 'unknown')
            reasoning = output.get('reasoning', 'Heuristic classification')
            return f"Intent → {intent} ({reasoning})"
        elif node_name == "summary":
            summary_text = output.get("summary_text")
            message_count = output.get("message_count", 0)
            if summary_text:
                return f"{message_count} messages summarized"
            return f"Summary skipped ({message_count} msgs)"
        elif node_name == "config_resolver":
            components = output.get("config_components", [])
            resolved = sum(1 for c in components if c.get("resolved"))
            fallback = len(components) - resolved
            parts = []
            if resolved:
                parts.append(f"{resolved} spec-matched")
            if fallback:
                parts.append(f"{fallback} search-fallback")
            not_found = output.get("config_validation_notes", [])
            missing = [n for n in not_found if "not found" in n.lower()]
            if missing:
                parts.append(f"{len(missing)} not found")
            return f"{len(components)} components ({', '.join(parts)})" if parts else f"{len(components)} components resolved"
        elif node_name == "config_generator":
            config = output.get("config_output", "")
            return f"Config generated ({len(config)} chars)"
        elif node_name == "config_response":
            return "Config response formatted"
        elif node_name == "doc_planner":
            sections = output.get("doc_outline", [])
            return f"{len(sections)} sections planned"
        elif node_name == "doc_gatherer":
            gathered = output.get("doc_sections_gathered", 0)
            total = output.get("doc_sections_total", 0)
            return f"{gathered}/{total} sections gathered"
        elif node_name == "doc_synthesizer":
            return "Documentation synthesized"
        return ""

    async def _generate_title(
        self,
        thread_id: str,
        user_message: str,
        response: Optional[str],
    ) -> Optional[str]:
        """Generate and save a conversation title."""
        try:
            loop = asyncio.get_event_loop()
            # update_conversation_title() uses the internally set thread_id
            # and handles both generation and database update
            await loop.run_in_executor(
                None,
                self._agent.update_conversation_title
            )
            # Return a generated title from the user message for the WebSocket event
            # (the actual title is saved to DB by update_conversation_title)
            return user_message[:50].strip() if user_message else None
        except Exception as e:
            print(f"Error generating title: {e}")
            return None

    async def cleanup(self):
        """
        Clean up resources held by the agent.

        This must be called before shutting down the service to properly
        release memory held by models (especially the reranker) and database
        connections.
        """
        if self._agent:
            try:
                # Close async pool first
                await self._agent.close_async_pool()
                # Call the agent's cleanup method which handles:
                # - Deleting reranker model from memory
                # - Clearing CUDA cache
                # - Closing database connection pool
                self._agent.cleanup()
                self._agent = None
            except Exception as e:
                print(f"Error during agent cleanup: {e}")
            finally:
                self._initialized = False
