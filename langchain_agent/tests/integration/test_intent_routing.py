#!/usr/bin/env python3
"""
Comprehensive intent and content type classification test suite.

Tests all 5 intents with multiple query variations:
- question (14 tests): Conversational Q&A
- config_request (10 tests): Pipeline configuration generation
- documentation_request (15 tests): Publication content with 5 content types:
  * social_post (3 tests): LinkedIn/Twitter posts (100-300 words)
  * blog_post (3 tests): Narrative articles (1000-2000 words)
  * technical_article (3 tests): Technical deep-dives (800-1500 words)
  * tutorial (3 tests): Step-by-step guides (1000 words)
  * comprehensive_docs (3 tests): Full reference docs (2000+ words)
- summary (5 tests): Conversation recap
- follow_up (7 tests): Acknowledgments and reactions

Uses fast testing mode: stops after intent classification for non-doc requests,
stops after content type classification for documentation_request.

Usage:
    # Requires backend running (./scripts/start.sh)
    python tests/test_intents.py

    # Or with explicit API key:
    API_KEY=your_key python tests/test_intents.py
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import websockets

# Load API key from environment or .env file
API_KEY = os.environ.get("API_KEY", "")
if not API_KEY:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("API_KEY="):
                API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

# WS_URL will be set in main() if API_KEY is available
WS_URL = f"ws://localhost:8000/ws/chat?api_key={API_KEY}" if API_KEY else ""

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class TestResult:
    """Captures full result of a single query test."""
    query: str
    expected_intent: str
    actual_intent: str = ""
    confidence: float = 0.0
    intent_reasoning: str = ""
    expected_content_type: Optional[str] = None  # For documentation_request tests
    actual_content_type: str = ""
    content_type_confidence: float = 0.0
    nodes_executed: List[str] = field(default_factory=list)
    node_durations: Dict[str, float] = field(default_factory=dict)
    event_types: List[str] = field(default_factory=list)
    event_details: Dict[str, Any] = field(default_factory=dict)
    final_response: str = ""
    total_events: int = 0
    total_time_ms: float = 0.0
    error: Optional[str] = None
    passed: bool = False


async def run_query(query: str, expected_intent: str, timeout: int = 180,
                    thread_id_override: Optional[str] = None,
                    intent_only: bool = False,
                    expected_content_type: Optional[str] = None) -> TestResult:
    """Send a query and collect all observability events.

    Args:
        query: Query text to send
        expected_intent: Expected intent classification
        timeout: Max wait time for response
        thread_id_override: Optional thread ID
        intent_only: If True, stop after intent classification (faster)
        expected_content_type: Expected content type (for documentation_request tests)
    """
    result = TestResult(query=query, expected_intent=expected_intent, expected_content_type=expected_content_type)
    start = time.time()

    try:
        async with websockets.connect(WS_URL) as ws:
            # Connection established
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            thread_id = thread_id_override or data.get("thread_id", "unknown")

            # Send query
            await ws.send(json.dumps({
                "type": "chat_message",
                "message": query,
                "thread_id": thread_id,
            }))

            # Collect events
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(msg)
                etype = data.get("type", "?")
                result.event_types.append(etype)
                result.total_events += 1

                # Track key events
                if etype == "intent_classification":
                    result.actual_intent = data.get("intent", "")
                    result.confidence = data.get("confidence", 0.0)
                    result.intent_reasoning = data.get("reasoning", "")

                    # If intent_only mode AND not a documentation request, stop here
                    # For documentation requests, we need to wait for content_type_classification
                    if intent_only and result.actual_intent != "documentation_request":
                        result.total_time_ms = (time.time() - start) * 1000
                        result.passed = (result.actual_intent == expected_intent)
                        return result

                elif etype == "clarification_requested":
                    # Human-in-the-loop clarification triggered
                    # Types: "format" (query missing format), "topic" (query missing topic)
                    clarification_type = data.get("clarification_type", "format")
                    result.event_details["clarification_type"] = clarification_type
                    result.event_details["clarification_reason"] = data.get("reason")

                    if clarification_type == "topic":
                        # Topic clarification: query lacks explicit subject
                        # Auto-respond with a default topic for testing
                        topic_response = "Lucille connectors and pipeline configuration"
                        result.event_details["clarification_topic_provided"] = topic_response

                        # Send topic response
                        await ws.send(json.dumps({
                            "type": "chat_message",
                            "message": topic_response,
                            "thread_id": thread_id,
                        }))
                        result.event_details["clarification_response"] = topic_response

                    elif clarification_type == "format":
                        # Format clarification: query missing content format specification
                        # Auto-respond by selecting the expected content type from candidates
                        candidates = data.get("candidates", [])
                        result.event_details["clarification_candidates"] = [c.get("type") for c in candidates]
                        result.event_details["clarification_threshold"] = data.get("threshold")

                        # Find which option matches expected_content_type
                        selection = "1"  # Default to first option
                        if result.expected_content_type:
                            for idx, candidate in enumerate(candidates, start=1):
                                if candidate.get("type") == result.expected_content_type:
                                    selection = str(idx)
                                    break

                        # Send clarification response
                        await ws.send(json.dumps({
                            "type": "chat_message",
                            "message": selection,
                            "thread_id": thread_id,
                        }))
                        result.event_details["clarification_response"] = selection

                    # Continue processing to get clarification_resolved and content_type_classification

                elif etype == "clarification_resolved":
                    result.event_details["clarification_user_selected"] = data.get("user_selected")
                    result.event_details["clarification_confidence_after"] = data.get("confidence_after")

                elif etype == "content_type_classification":
                    result.actual_content_type = data.get("content_type", "")
                    result.content_type_confidence = data.get("confidence", 0.0)
                    result.event_details["content_target_length"] = data.get("target_length")
                    result.event_details["content_tone"] = data.get("tone")
                    result.event_details["content_retrieval_depth"] = data.get("retrieval_depth")
                    result.event_details["content_temperature"] = data.get("temperature")

                    # If testing documentation requests, stop after content type classification
                    if intent_only and result.expected_content_type is not None:
                        result.total_time_ms = (time.time() - start) * 1000
                        intent_match = result.actual_intent == expected_intent
                        content_type_match = result.actual_content_type == result.expected_content_type
                        result.passed = intent_match and content_type_match and result.error is None
                        return result

                elif etype == "node_start":
                    node = data.get("node", "?")
                    result.nodes_executed.append(node)

                elif etype == "node_end":
                    node = data.get("node", "?")
                    dur = data.get("duration_ms", 0)
                    result.node_durations[node] = dur

                elif etype == "query_evaluation":
                    result.event_details["alpha"] = data.get("alpha")
                    result.event_details["search_strategy"] = data.get("search_strategy")
                    result.event_details["query_analysis"] = data.get("query_analysis", "")[:200]

                elif etype == "query_expansion":
                    result.event_details["expanded_query"] = data.get("expanded_query")
                    result.event_details["expansion_reason"] = data.get("expansion_reason")

                elif etype == "hybrid_search_result":
                    result.event_details["search_candidates"] = data.get("candidate_count", 0)

                elif etype == "reranker_result":
                    results_list = data.get("results", [])
                    if results_list:
                        result.event_details["top_reranker_score"] = results_list[0].get("score", 0)
                        result.event_details["reranked_count"] = len(results_list)

                elif etype == "alpha_refinement":
                    result.event_details["alpha_triggered"] = data.get("triggered")
                    result.event_details["alpha_max_score"] = data.get("max_score")

                elif etype == "config_builder_start":
                    result.event_details["config_request"] = data.get("user_request", "")[:100]

                elif etype == "component_spec_retrieval":
                    result.event_details["components_found"] = data.get("components_found", [])
                    result.event_details["components_not_found"] = data.get("components_not_found", [])

                elif etype == "config_generated":
                    result.event_details["config_component_count"] = data.get("component_count")
                    result.event_details["config_preview"] = data.get("config_preview", "")[:300]
                    result.event_details["validation_notes"] = data.get("validation_notes", [])

                elif etype == "doc_outline":
                    result.event_details["doc_sections"] = data.get("sections", [])
                    result.event_details["doc_total_components"] = data.get("total_components")

                elif etype == "doc_section_progress":
                    result.event_details["doc_progress"] = f"{data.get('sections_complete')}/{data.get('sections_total')}"
                    result.event_details["doc_components_gathered"] = data.get("components_gathered")

                elif etype == "doc_complete":
                    result.event_details["doc_total_sections"] = data.get("total_sections")
                    result.event_details["doc_components_documented"] = data.get("total_components_documented")
                    result.event_details["doc_length_chars"] = data.get("document_length_chars")

                elif etype == "summary_generated":
                    result.event_details["summary_message_count"] = data.get("message_count")

                elif etype == "agent_complete":
                    result.final_response = data.get("final_response", "")
                    result.event_details["citations"] = data.get("citations", [])
                    result.event_details["documents_used"] = data.get("documents_used", 0)
                    result.event_details["iterations"] = data.get("iterations", 0)
                    result.total_time_ms = data.get("total_duration_ms", 0)
                    break

                elif etype == "agent_error":
                    result.error = data.get("error", "Unknown error")
                    break

    except asyncio.TimeoutError:
        result.error = f"Timeout after {timeout}s"
    except Exception as e:
        result.error = str(e)

    result.total_time_ms = result.total_time_ms or (time.time() - start) * 1000
    # For intent_only mode, only check intent match and no errors
    result.passed = (
        result.actual_intent == expected_intent
        and result.error is None
    )
    return result


def print_result(result: TestResult, index: int):
    """Pretty-print a test result (simplified for intent_only mode)."""
    status = f"{GREEN}PASS{RESET}" if result.passed else f"{RED}FAIL{RESET}"

    # Intent
    intent_match = result.actual_intent == result.expected_intent
    intent_color = GREEN if intent_match else RED

    # Simplified one-line output for intent_only mode
    match_symbol = "✓" if intent_match else "✗"
    conf_display = f"{result.confidence:.0%}" if result.confidence > 0 else "N/A"
    time_display = f"{result.total_time_ms:.0f}ms" if result.total_time_ms > 0 else "N/A"

    print(f"  {status} {match_symbol} Expected: {CYAN}{result.expected_intent:25}{RESET} "
          f"Got: {intent_color}{result.actual_intent:25}{RESET} "
          f"Confidence: {conf_display:4}  Time: {time_display:6}")

    # If this is a documentation request test, also show content type
    if result.expected_content_type:
        content_type_match = result.actual_content_type == result.expected_content_type
        content_type_color = GREEN if content_type_match else RED
        content_match_symbol = "✓" if content_type_match else "✗"
        content_conf_display = f"{result.content_type_confidence:.0%}" if result.content_type_confidence > 0 else "N/A"

        print(f"       {content_match_symbol} Content Type - Expected: {CYAN}{result.expected_content_type:20}{RESET} "
              f"Got: {content_type_color}{result.actual_content_type:20}{RESET} "
              f"Confidence: {content_conf_display:4}")

    # Show error if present
    if result.error:
        print(f"    {RED}ERROR: {result.error}{RESET}")

    return result.passed


async def main():
    print(f"\n{BOLD}{'='*80}")
    print(f"  RUSTY COMPASS INTENT TEST SUITE")
    print(f"{'='*80}{RESET}\n")

    # Validate API key is available for CLI usage
    if not API_KEY:
        print("ERROR: API_KEY not found. Set API_KEY env var or ensure .env file exists.")
        return 1

    tests = [
        # ==================== QUESTION INTENT ====================
        # Conversational Q&A - direct answers expected

        # Basic questions
        ("What connectors are available in Lucille?", "question"),
        ("What's the difference between OpenSearchIndexer and ElasticsearchIndexer?", "question"),
        ("Can you explain how the RunMode interface works?", "question"),
        ("Which stages support embedding generation?", "question"),
        ("Tell me about the FileConnector", "question"),
        ("What are the requirements for custom stages?", "question"),
        ("How does Lucille handle error recovery?", "question"),
        ("What indexers work with vector search?", "question"),
        ("Explain the difference between connectors and stages", "question"),

        # Greetings and general queries
        ("Hello, what can you help me with?", "question"),
        ("Hi there!", "follow_up"),  # Greetings are continuation/greeting, not questions
        ("What's new in Lucille?", "question"),
        ("What can Lucille do?", "question"),

        # Troubleshooting and debugging questions
        ("How do I troubleshoot connection errors?", "question"),
        ("Why is my pipeline failing?", "question"),
        ("What causes timeout errors in connectors?", "question"),
        ("How do I debug stage execution?", "question"),

        # Best practices and recommendations
        ("What are best practices for pipeline design?", "question"),
        ("What's the recommended way to handle large files?", "question"),
        ("Should I use batch processing or streaming?", "question"),

        # Comparison questions
        ("Which is better: CSVConnector or FileConnector?", "question"),
        ("What's the difference between stages and indexers?", "question"),
        ("How does Lucille compare to other ETL tools?", "question"),

        # Edge cases - questions that could be confused with config_request
        ("How do I configure a stage?", "question"),  # Explanatory, not config generation
        ("What configuration options does CSVConnector have?", "question"),
        ("How should I set up my pipeline parameters?", "question"),
        ("What's the syntax for HOCON configs?", "question"),

        # Edge cases - questions that could be confused with documentation_request
        ("How do connectors work?", "question"),  # Asking for explanation, not docs
        ("What does the FileConnector do?", "question"),
        ("Can you explain vector embeddings?", "question"),

        # ==================== CONFIG_REQUEST INTENT ====================
        # Pipeline configuration generation - HOCON output expected

        # Explicit pipeline building
        ("Build me a CSV to Solr pipeline", "config_request"),
        ("Create a pipeline that reads from Kafka and writes to OpenSearch", "config_request"),
        ("Generate a pipeline config with CopyFields and SetStaticField stages", "config_request"),
        ("I need a pipeline configuration for PDF ingestion", "config_request"),
        ("Build me a CSV to Solr pipeline with CopyFields and SetStaticField stages", "config_request"),

        # Config generation variants
        ("Create a config for processing JSON files", "config_request"),
        ("Generate a Lucille pipeline that uses JlamaEmbed", "config_request"),
        ("Make me a pipeline with DatabaseConnector and ElasticsearchIndexer", "config_request"),
        ("Build a pipeline for vector search with embeddings", "config_request"),
        ("Create a HOCON config for document enrichment", "config_request"),

        # More pipeline requests
        ("Set up a pipeline from S3 to OpenSearch", "config_request"),
        ("Configure a data ingestion pipeline", "config_request"),
        ("I want a pipeline that uses the KafkaConnector", "config_request"),
        ("Give me a config for indexing documents", "config_request"),

        # Edge cases - imperative requests
        ("Pipeline for CSV files please", "config_request"),
        ("Need a config with embedding stage", "config_request"),

        # ==================== DOCUMENTATION_REQUEST INTENT ====================
        # Publication content - 5 content types with different lengths and depths

        # ---------- SOCIAL_POST (100-300 words) ----------
        ("Write a LinkedIn post about getting started with Lucille", "documentation_request", "social_post"),
        ("Create a short social media post highlighting CSVConnector features", "documentation_request", "social_post"),
        ("Draft a Twitter thread about Lucille's vector search capabilities", "documentation_request", "social_post"),
        ("Write a Facebook post about Lucille", "documentation_request", "social_post"),
        ("Create an Instagram caption about data pipelines", "documentation_request", "social_post"),
        ("Draft a LinkedIn announcement for Lucille 1.0", "documentation_request", "social_post"),

        # ---------- BLOG_POST (1000-2000 words) ----------
        ("Write a blog post about Lucille pipeline design patterns", "documentation_request", "blog_post"),
        ("Create a blog article exploring Lucille's hybrid search architecture", "documentation_request", "blog_post"),
        ("Draft a narrative blog post on building production data pipelines with Lucille", "documentation_request", "blog_post"),
        ("Write a blog about connector best practices", "documentation_request", "blog_post"),
        ("Create an engaging blog post about search relevancy", "documentation_request", "blog_post"),

        # ---------- TECHNICAL_ARTICLE (800-1500 words) ----------
        ("Write a technical article analyzing Lucille's cross-encoder reranking", "documentation_request", "technical_article"),
        ("Create a technical deep-dive on how Lucille handles vector embeddings", "documentation_request", "technical_article"),
        ("Draft a technical analysis of Lucille's connector architecture", "documentation_request", "technical_article"),
        ("Write a deep dive on the indexer implementation", "documentation_request", "technical_article"),
        ("Create a technical breakdown of the stage pipeline", "documentation_request", "technical_article"),

        # ---------- TUTORIAL (1000 words) ----------
        ("Write a step-by-step tutorial on creating a CSV to OpenSearch pipeline", "documentation_request", "tutorial"),
        ("Create a beginner's guide for building a Lucille pipeline", "documentation_request", "tutorial"),
        ("Draft a tutorial walking through custom stage development", "documentation_request", "tutorial"),
        ("Write a how-to guide for setting up vector search", "documentation_request", "tutorial"),
        ("Create a walkthrough for first-time users", "documentation_request", "tutorial"),
        ("Write step-by-step instructions for connector configuration", "documentation_request", "tutorial"),

        # ---------- COMPREHENSIVE_DOCS (2000+ words) ----------
        ("Document all available Lucille connectors with full specifications", "documentation_request", "comprehensive_docs"),
        ("Create comprehensive documentation for the Lucille indexer API", "documentation_request", "comprehensive_docs"),
        ("Write complete reference documentation for all Lucille stages", "documentation_request", "comprehensive_docs"),
        ("Document the SpecBuilder API", "documentation_request", "comprehensive_docs"),
        ("Draft API documentation for Lucille connectors", "documentation_request", "comprehensive_docs"),
        ("Create full reference docs for the pipeline system", "documentation_request", "comprehensive_docs"),
        ("Write exhaustive documentation covering all components", "documentation_request", "comprehensive_docs"),

        # ---------- EDGE CASES - Ambiguous format keywords ----------
        # "guide" is ambiguous (tutorial vs comprehensive_docs)
        # "article" is ambiguous (blog_post vs technical_article)
        # These test how the clarification system handles ambiguity

        # ==================== SUMMARY INTENT ====================
        # Conversation recap

        ("Summarize our conversation", "summary"),
        ("Can you recap what we discussed?", "summary"),
        ("Give me a summary of this chat", "summary"),
        ("What have we covered so far?", "summary"),
        ("Summarize the key points", "summary"),
        ("TL;DR of our chat", "summary"),
        ("Brief summary please", "summary"),
        ("Sum it up", "summary"),

        # ==================== FOLLOW_UP INTENT ====================
        # Acknowledgments and reactions

        # Simple acknowledgments
        ("OK, that makes sense", "follow_up"),
        ("Got it", "follow_up"),
        ("Thanks", "follow_up"),
        ("I see", "follow_up"),
        ("Perfect", "follow_up"),
        ("Understood", "follow_up"),
        ("Great", "follow_up"),
        ("Okay", "follow_up"),
        ("Alright", "follow_up"),
        ("Cool", "follow_up"),
        ("Nice", "follow_up"),

        # Gratitude
        ("Thank you!", "follow_up"),
        ("Thanks for the help", "follow_up"),
        ("Much appreciated", "follow_up"),

        # Confirmations
        ("Yes, that's what I needed", "follow_up"),
        ("That answers my question", "follow_up"),
        ("Makes sense now", "follow_up"),

        # Edge case - "Interesting" can be ambiguous
        ("Interesting", "follow_up"),

        # ==================== TASK INTENT ====================
        # Action requests with action verbs route to documentation_request
        # (action verbs like "show", "give", "provide" trigger docs generation)

        ("Show me an example of CSVConnector usage", "documentation_request"),
        ("Give me a code snippet for custom stages", "documentation_request"),
        ("Provide an example config", "documentation_request"),

        # ==================== EDGE CASES - VAGUE QUERIES ====================
        # These should trigger clarification (format or topic)
        # Note: The test harness auto-responds to clarifications

        # Vague format - missing content type specification
        # (LLM returns multiple types → triggers format clarification)
        # Uncomment these to test clarification flow:
        # ("Write about connectors", "documentation_request", "blog_post"),  # Vague format
        # ("Create content about Lucille", "documentation_request", "blog_post"),  # Vague format
        # ("Document pipelines", "documentation_request", "tutorial"),  # Vague format

        # Vague topic - missing subject
        # ("Write a blog post", "documentation_request", "blog_post"),  # Vague topic
        # ("Create a tutorial", "documentation_request", "tutorial"),  # Vague topic
    ]

    results = []
    passed = 0
    failed = 0

    for i, test_data in enumerate(tests, 1):
        # Handle both 2-element and 3-element tuples
        if len(test_data) == 2:
            query, expected_intent = test_data
            expected_content_type = None
        else:
            query, expected_intent, expected_content_type = test_data

        # Show test header
        if expected_content_type:
            print(f"\n{MAGENTA}▶ Running test {i}/{len(tests)}: [{expected_intent}/{expected_content_type}] {query[:60]}{RESET}")
        else:
            print(f"\n{MAGENTA}▶ Running test {i}/{len(tests)}: [{expected_intent}] {query[:80]}{RESET}")

        result = await run_query(query, expected_intent, intent_only=True, expected_content_type=expected_content_type)
        results.append(result)
        if print_result(result, i):
            passed += 1
        else:
            failed += 1

    # Summary
    print(f"\n\n{BOLD}{'='*80}")
    print(f"  TEST SUMMARY")
    print(f"{'='*80}{RESET}")
    print(f"\n  Total: {len(tests)}")
    print(f"  {GREEN}Passed: {passed}{RESET}")
    print(f"  {RED}Failed: {failed}{RESET}")

    # Summary by intent
    from collections import defaultdict
    by_intent = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    by_content_type = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})

    for r in results:
        by_intent[r.expected_intent]["total"] += 1
        if r.passed:
            by_intent[r.expected_intent]["passed"] += 1
        else:
            by_intent[r.expected_intent]["failed"] += 1

        # Track content type stats for documentation requests
        if r.expected_content_type:
            by_content_type[r.expected_content_type]["total"] += 1
            content_type_match = r.actual_content_type == r.expected_content_type
            if r.passed and content_type_match:
                by_content_type[r.expected_content_type]["passed"] += 1
            else:
                by_content_type[r.expected_content_type]["failed"] += 1

    print(f"\n  {BOLD}Results by Intent:{RESET}")
    for intent in ["question", "config_request", "documentation_request", "summary", "follow_up"]:
        if intent in by_intent:
            stats = by_intent[intent]
            color = GREEN if stats["failed"] == 0 else RED
            print(f"    {intent:25} {color}{stats['passed']}/{stats['total']} passed{RESET}")

    # Show content type breakdown if we tested documentation requests
    if by_content_type:
        print(f"\n  {BOLD}Results by Content Type (documentation_request):{RESET}")
        for content_type in ["social_post", "blog_post", "technical_article", "tutorial", "comprehensive_docs"]:
            if content_type in by_content_type:
                stats = by_content_type[content_type]
                color = GREEN if stats["failed"] == 0 else RED
                print(f"    {content_type:25} {color}{stats['passed']}/{stats['total']} passed{RESET}")

    print(f"\n  {BOLD}Individual Results:{RESET}")
    for i, r in enumerate(results, 1):
        status = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
        intent_match = "✓" if r.actual_intent == r.expected_intent else "✗"

        if r.expected_content_type:
            content_type_match = "✓" if r.actual_content_type == r.expected_content_type else "✗"
            print(f"  {status} Test {i}: [{r.expected_intent}/{r.expected_content_type}] → "
                  f"[{r.actual_intent}/{r.actual_content_type}] {intent_match}{content_type_match}  {r.query[:40]}")
        else:
            print(f"  {status} Test {i}: [{r.expected_intent}] → [{r.actual_intent}] {intent_match}  {r.query[:50]}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
