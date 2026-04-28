"""
Content generation nodes for multi-capability LangGraph agent.

This module provides lightweight content generators for different output formats:
- social_post: LinkedIn/Twitter posts (100-300 words)
- blog_post: Narrative articles (1000-2000 words)
- technical_article: Technical deep-dives (800-1500 words)
- tutorial: Step-by-step guides (1000 words)

The comprehensive_docs mode routes to the existing doc_writer pipeline.

All generators follow the same pattern:
1. Classify content type
2. Retrieve relevant documents
3. Generate content with appropriate tone/length
4. Emit progress events for UI streaming
"""

from typing import Any, Dict, TYPE_CHECKING
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent_state import CustomAgentState


class ContentTypeClassification(BaseModel):
    content_type: str
    confidence: float
    query_vagueness: str = "none"
    missing_info: str | None = None
    suggested_formats: list[str] | None = None
    suggested_topics: list[str] | None = None
    reasoning: str = ""
from api.schemas.events import (
    ContentTypeClassificationEvent,
    ClarificationRequestedEvent,
    ClarificationResolvedEvent,
    SocialPostProgressEvent,
    BlogPostProgressEvent,
    ArticleProgressEvent,
    TutorialProgressEvent,
    ContentCompleteEvent,
)

if TYPE_CHECKING:
    from main import LucilleAgent

logger = logging.getLogger(__name__)


def get_content_params(content_type: str) -> dict:
    """
    Get generation parameters for a content type.

    Args:
        content_type: One of "social_post", "blog_post", "technical_article",
                     "tutorial", "comprehensive_docs"

    Returns:
        Dictionary with target_length, tone, retrieval_depth, temperature,
        retrieval_k, retrieval_fetch_k, description (user-facing)
    """
    params_map = {
        "social_post": {
            "target_length": 200,  # words
            "tone": "engaging",
            "retrieval_depth": 1,  # single retrieval pass
            "temperature": 0.8,  # creative
            "retrieval_k": 3,  # fewer docs for concise content
            "retrieval_fetch_k": 10,
            "description": "Short, engaging post for LinkedIn/Twitter (100-300 words)",
        },
        "blog_post": {
            "target_length": 1500,
            "tone": "narrative",
            "retrieval_depth": 2,  # concepts + examples
            "temperature": 0.7,
            "retrieval_k": 10,
            "retrieval_fetch_k": 40,
            "description": "Narrative article with storytelling flow (1000-2000 words)",
        },
        "technical_article": {
            "target_length": 1200,
            "tone": "technical",
            "retrieval_depth": 3,  # problem + solution + implementation
            "temperature": 0.5,
            "retrieval_k": 10,
            "retrieval_fetch_k": 40,
            "description": "Technical deep-dive with implementation details (800-1500 words)",
        },
        "tutorial": {
            "target_length": 1000,
            "tone": "instructional",
            "retrieval_depth": 2,  # concepts + code examples
            "temperature": 0.4,  # precise instructions
            "retrieval_k": 10,
            "retrieval_fetch_k": 40,
            "description": "Step-by-step guide with code examples (~1000 words)",
        },
        "comprehensive_docs": {
            "target_length": 2500,
            "tone": "reference",
            "retrieval_depth": 5,  # full doc_writer pipeline
            "temperature": 0.3,
            "retrieval_k": 10,
            "retrieval_fetch_k": 40,
            "description": "Complete reference documentation (2000+ words)",
        },
    }

    return params_map.get(content_type, params_map["comprehensive_docs"])


def _is_vague_documentation_request(query: str, content_type: str) -> bool:
    """
    Detect if documentation request lacks an explicit topic/subject.

    Vague queries contain only the content type keyword without a subject.
    Examples:
    - "blog post" (vague - no topic)
    - "write a tutorial" (vague - tutorial about what?)
    - "create documentation" (vague - document what?)
    - "Write a LinkedIn post about Lucille" (NOT vague - has topic)

    Args:
        query: User's query
        content_type: Detected content type

    Returns:
        True if query is vague (lacks topic), False otherwise
    """
    query_lower = query.lower().strip()

    # Content type keywords that might appear alone
    content_keywords = {
        "social_post": ["linkedin", "twitter", "tweet", "social media", "social post", "facebook", "instagram", "post"],
        "blog_post": ["blog", "blog post", "article"],
        "technical_article": ["technical article", "deep dive", "deep-dive", "analysis"],
        "tutorial": ["tutorial", "guide", "walkthrough", "how to", "how-to"],
        "comprehensive_docs": ["documentation", "docs", "document", "reference"],
    }

    keywords = content_keywords.get(content_type, [])

    # Check if query is ONLY the content type keyword with minimal action verbs
    # Pattern: "write/create/draft + [content_type]" with nothing else
    action_verbs = ["write", "create", "draft", "make", "generate", "build", "produce"]

    # Remove action verbs and articles to get core query
    words = query_lower.split()
    core_words = [w for w in words if w not in action_verbs and w not in ["a", "an", "the", "me"]]

    # If core query is just 1-2 words and matches a content keyword, it's vague
    if len(core_words) <= 2:
        for keyword in keywords:
            # Check if the query is essentially just the keyword
            if keyword in query_lower:
                # Check if there's anything substantial after the keyword
                # Split on keyword and check remainder
                parts = query_lower.split(keyword)
                if len(parts) == 2:  # keyword found
                    remainder = parts[1].strip()
                    # If remainder is empty or just punctuation, it's vague
                    if not remainder or len(remainder.split()) == 0:
                        return True

    # Also check for bare keywords with minimal context
    bare_patterns = [
        "blog post",
        "blog",
        "article",
        "tutorial",
        "guide",
        "documentation",
        "docs",
        "linkedin post",
        "twitter post",
        "social post",
        "technical article",
    ]

    # Check if query matches bare patterns (with minimal surrounding words)
    for pattern in bare_patterns:
        if query_lower == pattern or query_lower in [f"write {pattern}", f"create {pattern}", f"draft {pattern}",
                                                       f"make {pattern}", f"write a {pattern}", f"create a {pattern}",
                                                       f"draft a {pattern}", f"make a {pattern}", f"write me {pattern}",
                                                       f"write me a {pattern}"]:
            return True

    return False


def content_type_classifier_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Classify the user's documentation request into one of 5 content types.

    Uses lightweight LLM (gemini-2.5-flash-lite) to detect content type based on:
    - Explicit keywords (social post, blog, article, tutorial, comprehensive)
    - Implied scope (short vs long, casual vs formal)
    - Action verbs (write, create, document, etc.)

    Phase 1: Defaults everything to "comprehensive_docs" to maintain existing behavior.
    Future phases will implement full classification logic.

    Args:
        state: Agent state with user query in messages
        agent: LucilleAgent instance for LLM access

    Returns:
        State updates with:
        - content_type: Detected type (currently always "comprehensive_docs")
        - content_type_confidence: Confidence score 0.0-1.0
        - content_target_length: Target word count
        - content_tone: Writing tone
        - content_retrieval_depth: Number of retrieval passes
        - content_temperature: LLM temperature for generation

    Emits:
        ContentTypeClassificationEvent: Classification results
    """
    logger.info("content_type_classifier_node: Starting content type classification")

    # Extract user query
    messages = state.get("messages", [])
    if not messages:
        logger.warning("No messages in state, defaulting to comprehensive_docs")
        content_type = "comprehensive_docs"
        confidence = 1.0
        reasoning = "No user query provided"
    else:
        # Extract last human message
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content if hasattr(msg, "content") else ""
                break

        # Track if query was expanded (for state updates later)
        expanded_query = None

        if not user_query:
            logger.warning("No user query found, defaulting to comprehensive_docs")
            content_type = "comprehensive_docs"
            confidence = 1.0
            reasoning = "No user query found in messages"
        else:
            # Expand vague queries with conversation context (e.g., "Write a Facebook post" → "Write a Facebook post about SpecBuilder API")
            expanded = agent._expand_vague_query(user_query, messages)
            if expanded != user_query:
                logger.info(f"Content type classifier: Expanded query '{user_query}' → '{expanded}'")
                expanded_query = expanded  # Store for state updates
                user_query = expanded  # Use expanded query for classification

            # LLM classifies content type only; vagueness is checked in code
            classification_prompt = f"""Classify this content request into one of 5 types. Respond as JSON only.

Request: "{user_query}"

Content types:
- social_post: LinkedIn, Twitter, Facebook, or any social media
- blog_post: Narrative blog articles (NOT LinkedIn/social)
- technical_article: Technical deep-dive analysis
- tutorial: Step-by-step how-to guides
- comprehensive_docs: API reference, formal documentation

IMPORTANT: "LinkedIn", "Twitter", "Facebook", or "social" → always social_post.

JSON response:
{{
  "content_type": "social_post|blog_post|technical_article|tutorial|comprehensive_docs",
  "confidence": 0.0-1.0,
  "reasoning": "Brief reason"
}}"""

            try:
                # Use structured output for content type classification
                # For Google Gemini, use invoke() for structured output (it handles streaming internally)
                structured_llm = agent.alpha_estimator_llm.with_structured_output(ContentTypeClassification)
                result = structured_llm.invoke(classification_prompt)

                content_type = result.content_type
                confidence = result.confidence
                reasoning = result.reasoning

                # Validate content type
                valid_types = ["social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"]
                if content_type not in valid_types:
                    logger.warning(f"Invalid content type '{content_type}', defaulting to comprehensive_docs")
                    content_type = "comprehensive_docs"
                    confidence = 0.5
                    reasoning = f"Invalid type returned, defaulting to comprehensive_docs"

            except Exception as e:
                logger.error(f"Error during content type classification: {e}", extra={
                    "error_type": type(e).__name__,
                    "query": user_query,
                    "model": str(agent.alpha_estimator_llm)
                })
                content_type = "comprehensive_docs"
                confidence = 0.5
                reasoning = f"Classification error: {str(e)}"

            logger.info(f"Classified as: {content_type} (confidence: {confidence:.2f})")

            # Code-based vagueness detection (LLM is unreliable for this)
            query_lower = user_query.lower()
            format_keywords = {
                "linkedin", "twitter", "facebook", "social", "blog", "article",
                "tutorial", "guide", "document", "documentation", "docs", "reference", "post",
                "how to", "how-to", "step by step", "step-by-step", "write",
            }
            topic_indicators = re.compile(
                r'\b(?:about|for|on|regarding|covering|explaining|the)\s+\S+', re.IGNORECASE
            )
            has_format = any(kw in query_lower for kw in format_keywords)
            has_topic = bool(topic_indicators.search(user_query))

            if has_format and has_topic:
                query_vagueness = "none"
            elif has_format and not has_topic:
                query_vagueness = "missing_topic"
            elif not has_format and has_topic:
                query_vagueness = "missing_format"
            else:
                query_vagueness = "missing_both"

            logger.info(f"Code-based vagueness: {query_vagueness} (has_format={has_format}, has_topic={has_topic})")

            # Handle vagueness
            if query_vagueness == "missing_format":
                # User didn't specify what type of content they want
                logger.info(f"Query missing format specification: '{user_query}'")

                # Provide all formats as options
                all_formats = ["social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"]
                format_options = []
                for idx, fmt in enumerate(all_formats, 1):
                    params = get_content_params(fmt)
                    format_options.append(
                        f"**{idx}. {fmt.replace('_', ' ').title()}**\n   {params['description']}\n   Length: ~{params['target_length']} words | Tone: {params['tone']}"
                    )

                clarification_text = f"""I can help you create content about that topic, but what format would you like?

{chr(10).join(format_options)}

Reply with the number or describe the format you want."""

                # Emit clarification requested event
                agent._emit_event_from_sync(
                    ClarificationRequestedEvent(
                        node="content_type_classifier",
                        clarification_type="format",
                        reason="Query doesn't specify content format",
                        candidates=[
                            {
                                "type": fmt,
                                "confidence": 0.0,
                                "description": get_content_params(fmt)['description'],
                            }
                            for fmt in all_formats
                        ],
                        threshold=1.0,
                        original_query=user_query,
                    )
                )

                return {
                    "messages": [AIMessage(content=clarification_text)],
                    "awaiting_clarification": True,
                    "clarification_type": "format",
                    "clarification_candidates": [(fmt, 0.0) for fmt in all_formats],
                }

            elif query_vagueness == "missing_topic":
                # User specified format but not topic
                logger.info(f"Query missing topic: '{user_query}'")

                # Build topic clarification message
                topic_examples = [
                    "Lucille connectors",
                    "OpenSearch vector search",
                    "Pipeline configuration best practices"
                ]

                clarification_text = f"""What topic would you like me to write about?

You asked for a **{content_type.replace('_', ' ')}**, but didn't specify the subject.

Please provide the topic. Examples:
{chr(10).join(f'- {topic}' for topic in topic_examples)}"""

                agent._emit_event_from_sync(
                    ClarificationRequestedEvent(
                        node="content_type_classifier",
                        clarification_type="topic",
                        reason="Query lacks explicit topic/subject",
                        candidates=[],  # No candidates for topic
                        threshold=1.0,
                        original_query=user_query,
                    )
                )

                return {
                    "messages": [AIMessage(content=clarification_text)],
                    "awaiting_clarification": True,
                    "clarification_type": "topic",
                    "content_type": content_type,  # Store for later
                    "content_type_confidence": confidence,
                }

            elif query_vagueness == "missing_both":
                # User gave minimal info - need both format and topic
                # Ask for format first (simpler flow)
                logger.info(f"Query missing both format and topic: '{user_query}'")

                # Build clarification message for format first
                all_formats = ["social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"]
                format_options = []
                for idx, fmt in enumerate(all_formats, 1):
                    params = get_content_params(fmt)
                    format_options.append(
                        f"**{idx}. {fmt.replace('_', ' ').title()}** - {params['description']}"
                    )

                clarification_text = f"""What type of content would you like?

{chr(10).join(format_options)}

Reply with the number or describe the format you want. I'll ask about the topic next."""

                agent._emit_event_from_sync(
                    ClarificationRequestedEvent(
                        node="content_type_classifier",
                        clarification_type="format",
                        reason="Query missing both format and topic",
                        candidates=[
                            {
                                "type": fmt,
                                "confidence": 0.0,
                                "description": get_content_params(fmt)['description'],
                            }
                            for fmt in all_formats
                        ],
                        threshold=1.0,
                        original_query=user_query,
                    )
                )

                return {
                    "messages": [AIMessage(content=clarification_text)],
                    "awaiting_clarification": True,
                    "clarification_type": "format",
                    "clarification_candidates": [(fmt, 0.0) for fmt in all_formats],
                }

            # If query_vagueness == "none", continue with normal flow below

    # Get content parameters
    params = get_content_params(content_type)

    # NOTE: Vagueness checking (missing format/topic) now handled by LLM analysis above
    # The LLM returns query_vagueness field which is processed earlier in this function

    # Emit classification event
    agent._emit_event_from_sync(
        ContentTypeClassificationEvent(
            content_type=content_type,
            confidence=confidence,
            target_length=params["target_length"],
            tone=params["tone"],
            retrieval_depth=params["retrieval_depth"],
            temperature=params["temperature"],
        )
    )

    # Update state (store expanded_query if expansion occurred)
    state_updates = {
        "content_type": content_type,
        "content_type_confidence": confidence,
        "content_target_length": params["target_length"],
        "content_tone": params["tone"],
        "content_retrieval_depth": params["retrieval_depth"],
        "content_temperature": params["temperature"],
    }

    # Store expanded query for generators to use (if expansion occurred)
    if expanded_query is not None:
        state_updates["expanded_query"] = expanded_query

    return state_updates


def format_clarification_resolver_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Parse user's clarification response and resolve content format.

    Called when query_vagueness was "missing_format" or "missing_both".
    Expects user to reply with:
    - "1", "2", "3" (numeric choice)
    - Content type name (e.g., "blog post", "tutorial")
    - Description keywords

    Args:
        state: Agent state with clarification_candidates
        agent: LucilleAgent instance

    Returns:
        State updates with resolved content_type and parameters
    """
    logger.info("format_clarification_resolver_node: Parsing user's format clarification response")

    # Get clarification candidates
    candidates = state.get("clarification_candidates", [])
    if not candidates or len(candidates) < 2:
        logger.warning("No clarification candidates found, using default")
        content_type = "comprehensive_docs"
        confidence = 1.0
    else:
        # Extract user's response from last message
        messages = state.get("messages", [])
        user_response = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_response = msg.content if hasattr(msg, "content") else ""
                break

        user_response_lower = user_response.lower().strip()
        logger.info(f"User clarification response: '{user_response}'")

        # Parse response
        content_type = None
        confidence = 1.0  # User-confirmed classification has 100% confidence

        # Check for numeric choice (1, 2, 3, etc.)
        if user_response_lower in ["1", "one", "first"]:
            content_type = candidates[0][0]
            logger.info(f"User selected option 1: {content_type}")
        elif user_response_lower in ["2", "two", "second"] and len(candidates) >= 2:
            content_type = candidates[1][0]
            logger.info(f"User selected option 2: {content_type}")
        elif user_response_lower in ["3", "three", "third"] and len(candidates) >= 3:
            content_type = candidates[2][0]
            logger.info(f"User selected option 3: {content_type}")
        else:
            # Check for content type keywords in response
            for candidate_type, _ in candidates:
                type_label = candidate_type.replace('_', ' ')
                if type_label in user_response_lower or candidate_type in user_response_lower:
                    content_type = candidate_type
                    logger.info(f"User mentioned '{candidate_type}' in response")
                    break

        # Default to first candidate if nothing matched
        if not content_type:
            content_type = candidates[0][0]
            logger.info(f"Could not parse response, defaulting to first candidate: {content_type}")

    # Get content parameters
    params = get_content_params(content_type)

    # Get original classification from state (before user clarification)
    original_classification = state.get("content_type", candidates[0][0] if candidates else "comprehensive_docs")
    confidence_before = state.get("content_type_confidence", candidates[0][1] if candidates else 0.5)

    # Emit clarification resolved event
    agent._emit_event_from_sync(
        ClarificationResolvedEvent(
            node="format_clarification_resolver",
            clarification_type="format",
            original_classification=original_classification,
            user_selected=content_type,
            confidence_before=confidence_before,
            confidence_after=1.0,  # User-confirmed
            user_response=user_response if 'user_response' in locals() else "",
        )
    )

    # Emit classification event (with user-confirmed confidence)
    agent._emit_event_from_sync(
        ContentTypeClassificationEvent(
            content_type=content_type,
            confidence=confidence,
            target_length=params["target_length"],
            tone=params["tone"],
            retrieval_depth=params["retrieval_depth"],
            temperature=params["temperature"],
        )
    )

    # Return state updates
    return {
        "content_type": content_type,
        "content_type_confidence": confidence,
        "content_target_length": params["target_length"],
        "content_tone": params["tone"],
        "content_retrieval_depth": params["retrieval_depth"],
        "content_temperature": params["temperature"],
        "awaiting_clarification": False,  # Clear flag
        "needs_clarification": False,  # Clear flag
    }


def topic_clarification_resolver_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Parse user's topic response and combine with content type.

    When user provides a vague query like "blog post", we ask for the topic.
    This node extracts the topic from their response and creates a complete query.

    Args:
        state: Agent state with content_type and user's topic response

    Returns:
        State updates with expanded_query for generators
    """
    logger.info("topic_clarification_resolver_node: Parsing user's topic response")

    # Get stored content type from state
    content_type = state.get("content_type", "comprehensive_docs")
    content_type_confidence = state.get("content_type_confidence", 1.0)

    # Extract user's topic from last message
    messages = state.get("messages", [])
    user_topic = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_topic = msg.content if hasattr(msg, "content") else ""
            break

    logger.info(f"User provided topic: '{user_topic}'")

    # Build complete query by combining content type with topic
    content_type_label = content_type.replace('_', ' ')
    complete_query = f"Write a {content_type_label} about {user_topic}"

    # Get content parameters
    params = get_content_params(content_type)

    # Emit clarification resolved event
    agent._emit_event_from_sync(
        ClarificationResolvedEvent(
            node="format_clarification_resolver",
            clarification_type="topic",
            original_classification=content_type,
            user_selected=content_type,  # Same type, just added topic
            confidence_before=content_type_confidence,
            confidence_after=1.0,  # User-confirmed with topic
            user_response=user_topic,
        )
    )

    # Emit classification event (with complete query)
    agent._emit_event_from_sync(
        ContentTypeClassificationEvent(
            content_type=content_type,
            confidence=1.0,  # User-confirmed
            target_length=params["target_length"],
            tone=params["tone"],
            retrieval_depth=params["retrieval_depth"],
            temperature=params["temperature"],
        )
    )

    # Return state with expanded query
    return {
        "content_type": content_type,
        "content_type_confidence": 1.0,
        "content_target_length": params["target_length"],
        "content_tone": params["tone"],
        "content_retrieval_depth": params["retrieval_depth"],
        "content_temperature": params["temperature"],
        "expanded_query": complete_query,  # Complete query with topic
        "awaiting_clarification": False,
        "needs_clarification": False,
    }


def social_content_generator_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Generate a social media post (100-300 words).

    Single retrieval pass with semantic-heavy weighting (α=0.6) to get
    conceptual information. Generates engaging, concise content with:
    - Hook (attention-grabbing opening)
    - Key insight (1-2 main points)
    - CTA (call-to-action or takeaway)

    Args:
        state: Agent state with user query
        agent: LucilleAgent instance

    Returns:
        State updates with:
        - messages: AIMessage with generated social post
        - content_output: Generated post text

    Emits:
        - SocialPostProgressEvent (retrieval, generation stages)
        - ContentCompleteEvent (final metrics)
    """
    logger.info("social_content_generator_node: Starting social post generation")

    # Extract user query (prefer expanded_query if available)
    messages = state.get("messages", [])
    user_query = state.get("expanded_query")  # Use expanded query if available

    if not user_query:
        # Fall back to extracting from messages
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content if hasattr(msg, "content") else ""
                break

    if not user_query:
        logger.error("No user query found")
        error_msg = "Error: No user query provided for social post generation"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }

    logger.info(f"Social post generation: Using query '{user_query[:100]}...'")  # Log what query we're using

    # Get content parameters
    params = get_content_params("social_post")
    target_length = params["target_length"]
    temperature = params["temperature"]
    retrieval_k = params["retrieval_k"]
    retrieval_fetch_k = params["retrieval_fetch_k"]

    # Stage 1: Retrieval
    agent._emit_event_from_sync(
        SocialPostProgressEvent(
            stage="retrieval",
            message=f"Retrieving relevant information (semantic search, k={retrieval_k})..."
        )
    )

    try:
        # Single retrieval pass (semantic-heavy α=0.6)
        retrieved_docs = agent.vector_store.hybrid_search(
            query=user_query,
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.6,  # Semantic-heavy for conceptual understanding
        )

        if not retrieved_docs:
            logger.warning("No documents retrieved for social post")
            context = "No specific information found."
        else:
            # Format context from retrieved documents
            context_parts = []
            for i, doc in enumerate(retrieved_docs, 1):
                content = doc.page_content[:300] if doc.page_content else ""  # Limit to 300 chars per doc
                source = doc.metadata.get("source", "Unknown")
                context_parts.append(f"[{i}] {content} (Source: {source})")

            context = "\n\n".join(context_parts)
            logger.info(f"Retrieved {len(retrieved_docs)} documents for social post")

    except Exception as e:
        logger.error(f"Error during retrieval: {e}")
        context = "Error retrieving information."

    # Stage 2: Generation
    agent._emit_event_from_sync(
        SocialPostProgressEvent(
            stage="generation",
            message=f"Generating engaging social post (~{target_length} words)..."
        )
    )

    try:
        # Build generation prompt
        generation_prompt = f"""You are a social media content creator. Create an engaging, concise social media post (LinkedIn/Twitter style).

User request: "{user_query}"

Retrieved context:
{context}

IMPORTANT GUIDELINES:
- Length: Aim for {target_length} words (100-300 words max)
- Tone: Engaging, conversational, authentic
- Structure: Hook → Key Insight → Takeaway/CTA
- Use short paragraphs (1-2 sentences each)
- Include 1-2 key technical points if relevant
- End with a question, insight, or call-to-action
- NO hashtags (unless specifically requested)
- NO emoji (unless specifically requested)
- Be specific and actionable

Generate the social post now:"""

        # Generate using agent's LLM (astream_events handles token streaming)
        response = agent.llm.invoke(generation_prompt)
        content = response.content.strip() if hasattr(response, "content") else str(response)
        word_count = len(content.split())

        # Calculate metrics
        char_count = len(content)

        logger.info(f"Generated social post: {word_count} words, {char_count} chars")

        # Emit completion event
        agent._emit_event_from_sync(
            ContentCompleteEvent(
                node="social_content_generator",
                content_type="social_post",
                content_length_words=word_count,
                content_length_chars=char_count,
            )
        )

        return {
            "messages": [AIMessage(content=content)],
            "content_output": content,
        }

    except Exception as e:
        logger.error(f"Error during generation: {e}")
        error_msg = f"Error generating social post: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }


def blog_content_generator_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Generate a blog post (1000-2000 words).

    Multi-pass retrieval and generation:
    1. Create outline from query
    2. Retrieval pass 1: Conceptual information (α=0.7 semantic)
    3. Retrieval pass 2: Examples and use cases (α=0.3 lexical)
    4. Generate narrative blog post with markdown headers

    Args:
        state: Agent state with user query
        agent: LucilleAgent instance

    Returns:
        State updates with:
        - messages: AIMessage with generated blog post
        - content_output: Generated blog content

    Emits:
        - BlogPostProgressEvent (outline, retrieval_pass_1, retrieval_pass_2, generation)
        - ContentCompleteEvent (final metrics)
    """
    logger.info("blog_content_generator_node: Starting blog post generation")

    # Extract user query (prefer expanded_query if available)
    messages = state.get("messages", [])
    user_query = state.get("expanded_query")  # Use expanded query if available

    if not user_query:
        # Fall back to extracting from messages
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content if hasattr(msg, "content") else ""
                break

    logger.info(f"Blog post generation: Using query '{user_query[:100] if user_query else 'NONE'}...'")  # Log what query we're using

    if not user_query:
        logger.error("No user query found")
        error_msg = "Error: No user query provided for blog post generation"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }

    # Get content parameters
    params = get_content_params("blog_post")
    target_length = params["target_length"]
    temperature = params["temperature"]
    retrieval_k = params["retrieval_k"]
    retrieval_fetch_k = params["retrieval_fetch_k"]

    try:
        # Stage 1: Create outline
        agent._emit_event_from_sync(
            BlogPostProgressEvent(
                stage="outline",
                message="Creating blog post outline..."
            )
        )

        outline_prompt = f"""Create a brief outline for a blog post based on this request:

"{user_query}"

Respond with 3-4 section headings that would make a compelling narrative blog post.
Format as a simple list, one heading per line. Be concise (5-10 words per heading).

Example format:
- Introduction to the problem
- How X solves the challenge
- Real-world use cases
- Getting started guide

Your outline:"""

        outline_response = agent.alpha_estimator_llm.invoke(outline_prompt)
        outline = outline_response.content if hasattr(outline_response, "content") else str(outline_response)
        outline = outline.strip()

        logger.info(f"Generated outline: {outline[:100]}...")

        # Stage 2: Retrieval pass 1 - Concepts (semantic-heavy)
        agent._emit_event_from_sync(
            BlogPostProgressEvent(
                stage="retrieval_pass_1",
                message=f"Retrieving conceptual information (α=0.7, k={retrieval_k})..."
            )
        )

        concepts_docs = agent.vector_store.hybrid_search(
            query=user_query + " concepts architecture overview",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.7,  # Semantic-heavy for concepts
        )

        # Stage 3: Retrieval pass 2 - Examples (lexical-heavy)
        agent._emit_event_from_sync(
            BlogPostProgressEvent(
                stage="retrieval_pass_2",
                message=f"Retrieving examples and use cases (α=0.3, k={retrieval_k})..."
            )
        )

        examples_docs = agent.vector_store.hybrid_search(
            query=user_query + " examples usage code",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.3,  # Lexical-heavy for specific examples
        )

        # Combine and deduplicate documents
        all_docs = concepts_docs + examples_docs
        seen_content = set()
        unique_docs = []
        for doc in all_docs:
            content_hash = hash((doc.page_content or "")[:200])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append(doc)

        logger.info(f"Retrieved {len(unique_docs)} unique documents ({len(concepts_docs)} concepts, {len(examples_docs)} examples)")

        # Format context
        context_parts = []
        for i, doc in enumerate(unique_docs[:15], 1):  # Limit to top 15
            content = (doc.page_content or "")[:400]
            source = doc.metadata.get("source", "Unknown")
            context_parts.append(f"[{i}] {content}\n(Source: {source})")

        context = "\n\n".join(context_parts)

        # Stage 4: Generation
        agent._emit_event_from_sync(
            BlogPostProgressEvent(
                stage="generation",
                message=f"Generating narrative blog post (~{target_length} words)..."
            )
        )

        generation_prompt = f"""You are a technical blog writer. Create an engaging, narrative blog post.

User request: "{user_query}"

Outline to follow:
{outline}

Retrieved context:
{context}

IMPORTANT GUIDELINES:
- Length: Aim for {target_length} words (1000-2000 words)
- Tone: Narrative, storytelling, approachable yet technical
- Structure: Follow the outline with markdown headers (## for sections)
- Style: Use analogies, real-world scenarios, personal insights
- Format: Short paragraphs (2-4 sentences), natural flow
- Include: Code snippets or technical details where relevant
- Opening: Start with a relatable scenario or question
- Closing: End with actionable takeaways or next steps

Write the complete blog post now:"""

        # Generate using agent's LLM (astream_events handles token streaming)
        response = agent.llm.invoke(generation_prompt)
        content = response.content.strip() if hasattr(response, "content") else str(response)
        word_count = len(content.split())

        # Calculate metrics
        char_count = len(content)

        logger.info(f"Generated blog post: {word_count} words, {char_count} chars")

        # Emit completion event
        agent._emit_event_from_sync(
            ContentCompleteEvent(
                node="blog_content_generator",
                content_type="blog_post",
                content_length_words=word_count,
                content_length_chars=char_count,
            )
        )

        return {
            "messages": [AIMessage(content=content)],
            "content_output": content,
        }

    except Exception as e:
        logger.error(f"Error during blog generation: {e}")
        error_msg = f"Error generating blog post: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }


def article_content_generator_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Generate a technical article (800-1500 words).

    Deep-dive multi-pass retrieval and generation:
    1. Create outline (problem → solution → implementation)
    2. Retrieval pass 1: Problem space and context (α=0.5 balanced)
    3. Retrieval pass 2: Solution patterns and approaches (α=0.4 balanced)
    4. Retrieval pass 3: Implementation details and code (α=0.3 lexical)
    5. Generate technical deep-dive with code examples

    Args:
        state: Agent state with user query
        agent: LucilleAgent instance

    Returns:
        State updates with:
        - messages: AIMessage with generated technical article
        - content_output: Generated article content

    Emits:
        - ArticleProgressEvent (outline, retrieval_pass_1, retrieval_pass_2, retrieval_pass_3, generation)
        - ContentCompleteEvent (final metrics)
    """
    logger.info("article_content_generator_node: Starting technical article generation")

    # Extract user query (prefer expanded_query if available)
    messages = state.get("messages", [])
    user_query = state.get("expanded_query")  # Use expanded query if available

    if not user_query:
        # Fall back to extracting from messages
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content if hasattr(msg, "content") else ""
                break

    if not user_query:
        logger.error("No user query found")
        error_msg = "Error: No user query provided for technical article generation"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }

    logger.info(f"Technical article generation: Using query '{user_query[:100]}...'")  # Log what query we're using

    # Get content parameters
    params = get_content_params("technical_article")
    target_length = params["target_length"]
    temperature = params["temperature"]
    retrieval_k = params["retrieval_k"]
    retrieval_fetch_k = params["retrieval_fetch_k"]

    try:
        # Stage 1: Create outline
        agent._emit_event_from_sync(
            ArticleProgressEvent(
                stage="outline",
                message="Creating technical article outline (problem → solution → implementation)..."
            )
        )

        outline_prompt = f"""Create a technical article outline based on this request:

"{user_query}"

Respond with 3 main sections that follow this structure:
1. Problem Space / Context (what challenge or topic)
2. Solution / Approach (how it works, architecture, design)
3. Implementation / Deep Dive (technical details, code, examples)

Format as a simple list, one section per line. Be specific and technical.

Example format:
- The Challenge: Understanding hybrid search tradeoffs
- The Solution: Lucille's adaptive alpha weighting system
- Deep Dive: Implementation details and performance optimization

Your outline:"""

        outline_response = agent.alpha_estimator_llm.invoke(outline_prompt)
        outline = outline_response.content if hasattr(outline_response, "content") else str(outline_response)
        outline = outline.strip()

        logger.info(f"Generated outline: {outline[:100]}...")

        # Stage 2: Retrieval pass 1 - Problem space (balanced)
        agent._emit_event_from_sync(
            ArticleProgressEvent(
                stage="retrieval_pass_1",
                message=f"Retrieving problem space and context (α=0.5, k={retrieval_k})..."
            )
        )

        problem_docs = agent.vector_store.hybrid_search(
            query=user_query + " problem challenge context background",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.5,  # Balanced for problem understanding
        )

        # Stage 3: Retrieval pass 2 - Solution patterns (balanced)
        agent._emit_event_from_sync(
            ArticleProgressEvent(
                stage="retrieval_pass_2",
                message=f"Retrieving solution patterns and architecture (α=0.4, k={retrieval_k})..."
            )
        )

        solution_docs = agent.vector_store.hybrid_search(
            query=user_query + " solution approach architecture design pattern",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.4,  # Balanced for architectural concepts
        )

        # Stage 4: Retrieval pass 3 - Implementation details (lexical-heavy)
        agent._emit_event_from_sync(
            ArticleProgressEvent(
                stage="retrieval_pass_3",
                message=f"Retrieving implementation details and code (α=0.3, k={retrieval_k})..."
            )
        )

        implementation_docs = agent.vector_store.hybrid_search(
            query=user_query + " implementation code example API method class",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.3,  # Lexical-heavy for specific code/APIs
        )

        # Combine and deduplicate documents
        all_docs = problem_docs + solution_docs + implementation_docs
        seen_content = set()
        unique_docs = []
        for doc in all_docs:
            content_hash = hash((doc.page_content or "")[:200])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append(doc)

        logger.info(f"Retrieved {len(unique_docs)} unique documents ({len(problem_docs)} problem, {len(solution_docs)} solution, {len(implementation_docs)} implementation)")

        # Format context - keep it concise to leave room for generation
        context_parts = []
        for i, doc in enumerate(unique_docs[:10], 1):
            content = (doc.page_content or "")[:300]
            source = doc.metadata.get("source", "Unknown")
            context_parts.append(f"[{i}] {content}\n(Source: {source})")

        context = "\n\n".join(context_parts)

        # Stage 5: Generation
        agent._emit_event_from_sync(
            ArticleProgressEvent(
                stage="generation",
                message=f"Generating technical deep-dive article (~{target_length} words)..."
            )
        )

        generation_prompt = f"""You are a technical writer. Write a COMPLETE, DETAILED technical article of AT LEAST {target_length} words.

User request: "{user_query}"

Article outline:
{outline}

Reference material:
{context}

CRITICAL: The article MUST be at least {target_length} words (800-1500 words). Do NOT write a short summary. Each section must be multiple paragraphs with detailed analysis.

Guidelines:
- Structure: Use markdown ## headers for each outline section
- Tone: Technical, analytical, authoritative
- Each section: 3-5 paragraphs minimum with specific details
- Include: Code snippets, API examples, class/method names where relevant
- Include: Performance considerations and tradeoffs
- Opening: Problem statement or technical context (2-3 paragraphs)
- Middle: Detailed solution analysis (4-6 paragraphs)
- Closing: Key insights, best practices, next steps (2-3 paragraphs)

Write the complete technical article now. Remember: at least {target_length} words."""

        # Generate using agent's LLM (astream_events handles token streaming)
        response = agent.llm.invoke(generation_prompt)
        content = response.content.strip() if hasattr(response, "content") else str(response)
        word_count = len(content.split())

        # Calculate metrics
        char_count = len(content)

        logger.info(f"Generated technical article: {word_count} words, {char_count} chars")

        # Emit completion event
        agent._emit_event_from_sync(
            ContentCompleteEvent(
                node="article_content_generator",
                content_type="technical_article",
                content_length_words=word_count,
                content_length_chars=char_count,
            )
        )

        return {
            "messages": [AIMessage(content=content)],
            "content_output": content,
        }

    except Exception as e:
        logger.error(f"Error during technical article generation: {e}")
        error_msg = f"Error generating technical article: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }


def tutorial_generator_node(state: CustomAgentState, agent: "LucilleAgent") -> Dict[str, Any]:
    """
    Generate a step-by-step tutorial (~1000 words).

    Multi-pass retrieval and generation:
    1. Create step-by-step outline
    2. Retrieval pass 1: Conceptual background (α=0.6)
    3. Retrieval pass 2: Code examples and implementation (α=0.3)
    4. Generate instructional tutorial with numbered steps

    Args:
        state: Agent state with user query
        agent: LucilleAgent instance

    Returns:
        State updates with:
        - messages: AIMessage with generated tutorial
        - content_output: Generated tutorial content

    Emits:
        - TutorialProgressEvent (outline, concept_retrieval, example_retrieval, generation)
        - ContentCompleteEvent (final metrics)
    """
    logger.info("tutorial_generator_node: Starting tutorial generation")

    # Extract user query (prefer expanded_query if available)
    messages = state.get("messages", [])
    user_query = state.get("expanded_query")  # Use expanded query if available

    if not user_query:
        # Fall back to extracting from messages
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = msg.content if hasattr(msg, "content") else ""
                break

    if not user_query:
        logger.error("No user query found")
        error_msg = "Error: No user query provided for tutorial generation"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }

    logger.info(f"Tutorial generation: Using query '{user_query[:100]}...'")  # Log what query we're using

    # Get content parameters
    params = get_content_params("tutorial")
    target_length = params["target_length"]
    temperature = params["temperature"]
    retrieval_k = params["retrieval_k"]
    retrieval_fetch_k = params["retrieval_fetch_k"]

    try:
        # Stage 1: Create outline
        agent._emit_event_from_sync(
            TutorialProgressEvent(
                stage="outline",
                message="Creating tutorial outline with steps..."
            )
        )

        outline_prompt = f"""Create a step-by-step outline for a tutorial based on this request:

"{user_query}"

Respond with 4-6 numbered steps that would make a clear, actionable tutorial.
Each step should be a specific action. Format as a numbered list.

Example format:
1. Set up your environment
2. Install required dependencies
3. Configure the connector
4. Write your first pipeline
5. Test and verify results

Your tutorial steps:"""

        outline_response = agent.alpha_estimator_llm.invoke(outline_prompt)
        outline = outline_response.content if hasattr(outline_response, "content") else str(outline_response)
        outline = outline.strip()

        logger.info(f"Generated tutorial outline: {outline[:100]}...")

        # Stage 2: Retrieval pass 1 - Concepts
        agent._emit_event_from_sync(
            TutorialProgressEvent(
                stage="concept_retrieval",
                message=f"Retrieving conceptual background (α=0.6, k={retrieval_k})..."
            )
        )

        concepts_docs = agent.vector_store.hybrid_search(
            query=user_query + " overview concepts how to",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.6,  # Balanced for concepts
        )

        # Stage 3: Retrieval pass 2 - Code examples
        agent._emit_event_from_sync(
            TutorialProgressEvent(
                stage="example_retrieval",
                message=f"Retrieving code examples (α=0.3, k={retrieval_k})..."
            )
        )

        examples_docs = agent.vector_store.hybrid_search(
            query=user_query + " example code implementation",
            k=retrieval_k,
            fetch_k=retrieval_fetch_k,
            alpha=0.3,  # Lexical-heavy for code examples
        )

        # Combine and deduplicate documents
        all_docs = concepts_docs + examples_docs
        seen_content = set()
        unique_docs = []
        for doc in all_docs:
            content_hash = hash((doc.page_content or "")[:200])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append(doc)

        logger.info(f"Retrieved {len(unique_docs)} unique documents ({len(concepts_docs)} concepts, {len(examples_docs)} examples)")

        # Format context
        context_parts = []
        for i, doc in enumerate(unique_docs[:15], 1):
            content = doc.page_content[:400]
            source = doc.metadata.get("source", "Unknown")
            context_parts.append(f"[{i}] {content}\n(Source: {source})")

        context = "\n\n".join(context_parts)

        # Stage 4: Generation
        agent._emit_event_from_sync(
            TutorialProgressEvent(
                stage="generation",
                message=f"Generating step-by-step tutorial (~{target_length} words)..."
            )
        )

        generation_prompt = f"""You are a technical instructor. Create a clear, actionable tutorial.

User request: "{user_query}"

Tutorial steps to follow:
{outline}

Retrieved context:
{context}

IMPORTANT GUIDELINES:
- Length: Aim for {target_length} words (~1000 words)
- Tone: Instructional, clear, encouraging
- Structure: Numbered steps with clear headers
- Format: Each step should have:
  * Step number and title (## Step 1: Title)
  * Brief explanation (what and why)
  * Specific instructions (how to do it)
  * Code examples or commands (if applicable)
  * Expected result or verification
- Style: Direct, second-person ("you will...", "run this command...")
- Include: Prerequisites section at the start
- Include: Troubleshooting tips where relevant
- Closing: Next steps or additional resources

Write the complete tutorial now:"""

        # Generate using agent's LLM (astream_events handles token streaming)
        response = agent.llm.invoke(generation_prompt)
        content = response.content.strip() if hasattr(response, "content") else str(response)
        word_count = len(content.split())

        # Calculate metrics
        char_count = len(content)

        logger.info(f"Generated tutorial: {word_count} words, {char_count} chars")

        # Emit completion event
        agent._emit_event_from_sync(
            ContentCompleteEvent(
                node="tutorial_generator",
                content_type="tutorial",
                content_length_words=word_count,
                content_length_chars=char_count,
            )
        )

        return {
            "messages": [AIMessage(content=content)],
            "content_output": content,
        }

    except Exception as e:
        logger.error(f"Error during tutorial generation: {e}")
        error_msg = f"Error generating tutorial: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "content_output": error_msg,
        }
