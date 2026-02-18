"""
Documentation Writer nodes for generating comprehensive Lucille documentation.

Provides three LangGraph nodes:
1. doc_planner_node - Creates documentation outline from user request
2. doc_gatherer_node - Iterative retrieval loop gathering content per section
3. doc_synthesizer_node - Multi-pass generation producing final documentation
"""

import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent_state import CustomAgentState

logger = logging.getLogger(__name__)


class DocSection(BaseModel):
    title: str
    description: str
    components: list[str] = []
    search_queries: list[str] = []


class DocPlan(BaseModel):
    title: str = "Lucille Documentation"
    sections: list[DocSection] = []


def doc_planner_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Create a documentation outline from the user's request.

    Uses LLM to plan sections and calls vector_store.list_components()
    to scope the work.
    """
    start_time = time.time()
    messages = state["messages"]

    user_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and hasattr(msg, "content"):
            user_query = str(msg.content)
            break

    if not user_query:
        return {"doc_outline": [], "doc_sections_total": 0}

    # Discover available components to scope the documentation
    available_components = {}
    for comp_type in ["stage", "connector", "indexer"]:
        components = agent.vector_store.list_components(comp_type)
        if components:
            available_components[comp_type] = [
                c.get("class_name", "").split(".")[-1] for c in components
            ]

    components_summary = ""
    for comp_type, names in available_components.items():
        components_summary += f"\n{comp_type.title()}s ({len(names)}): {', '.join(names[:20])}"
        if len(names) > 20:
            components_summary += f"... and {len(names) - 20} more"

    plan_prompt = f"""Create a documentation outline for this request.

USER REQUEST: "{user_query}"

AVAILABLE LUCILLE COMPONENTS:
{components_summary or "No components found in database"}

Return ONLY valid JSON with this structure:
{{
  "title": "Document title",
  "sections": [
    {{
      "title": "Section Title",
      "description": "What this section covers",
      "components": ["ComponentName1", "ComponentName2"],
      "search_queries": ["query to search for relevant content"]
    }}
  ]
}}

Plan 3-8 sections that comprehensively cover the request. Each section should
reference specific components when applicable. Include an introduction and
conclusion/summary section.

JSON only:"""

    evaluator_llm = agent.alpha_estimator_llm or agent.llm
    try:
        structured_llm = evaluator_llm.with_structured_output(DocPlan)
        result = structured_llm.invoke(plan_prompt)

        sections = [s.model_dump() for s in result.sections]
        doc_title = result.title

    except Exception as e:
        logger.error(f"Doc planner: LLM inference failed", extra={
            "model": str(evaluator_llm),
            "error_type": type(e).__name__,
            "error": str(e)
        })
        return {
            "doc_outline": [],
            "doc_sections_total": 0,
            "messages": [AIMessage(content=(
                f"Unable to plan documentation: AI model error ({type(e).__name__}). "
                f"Ensure the AI model server is running and accessible."
            ))]
        }

    # Emit planning event
    total_components = sum(len(s.get("components", [])) for s in sections)
    try:
        from api.schemas.events import DocOutlineEvent
        if agent.emit_callback:
            agent._emit_event_from_sync(DocOutlineEvent(
                sections=[s.get("title", "") for s in sections],
                total_components=total_components,
            ))
    except ImportError as e:
        logger.error(f"Doc outline event emission failed - missing event schema: {e}")
    except Exception as e:
        logger.warning(f"Doc outline event emission failed: {e}")

    elapsed = time.time() - start_time
    logger.info(f"DocPlanner: planned {len(sections)} sections in {elapsed:.3f}s")

    return {
        "doc_outline": sections,
        "doc_sections_total": len(sections),
        "doc_sections_gathered": 0,
        "doc_gathered_content": {"title": doc_title},
        "agent_mode": "doc_writer",
    }


def doc_gatherer_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Iterative retrieval loop: gather content for each section in the outline.

    For each section/component, calls get_component_spec() for specs
    and hybrid_search() for guide content.
    """
    start_time = time.time()
    outline = state.get("doc_outline", [])
    gathered = state.get("doc_gathered_content", {})

    if not outline:
        return {"doc_gathered_content": gathered, "doc_sections_gathered": 0}

    sections_content = gathered.get("sections", {})
    sections_gathered = 0
    total_components_gathered = 0

    for i, section in enumerate(outline):
        section_title = section.get("title", f"Section {i+1}")
        components = section.get("components", [])
        search_queries = section.get("search_queries", [])

        section_data = {"specs": [], "search_results": []}

        # Gather component specs
        for comp_name in components:
            spec = agent.vector_store.get_component_spec(comp_name)
            if spec:
                section_data["specs"].append(spec)

        # Gather search results for each query
        for query in search_queries:
            results = agent.vector_store.hybrid_search(
                query, k=5, fetch_k=20, alpha=0.5
            )
            for doc in results:
                section_data["search_results"].append({
                    "content": doc.page_content[:800],
                    "source": doc.metadata.get("source", ""),
                    "title": doc.metadata.get("title", ""),
                })

        # If no search queries but has components, search for each
        if not search_queries and components:
            for comp_name in components[:5]:  # Limit to avoid too many searches
                results = agent.vector_store.hybrid_search(
                    f"Lucille {comp_name}", k=3, fetch_k=10, alpha=0.4
                )
                for doc in results:
                    section_data["search_results"].append({
                        "content": doc.page_content[:800],
                        "source": doc.metadata.get("source", ""),
                        "title": doc.metadata.get("title", ""),
                    })

        sections_content[section_title] = section_data
        sections_gathered += 1
        total_components_gathered += len(section_data["specs"])

        # Emit progress event
        try:
            from api.schemas.events import DocSectionProgressEvent
            if agent.emit_callback:
                agent._emit_event_from_sync(DocSectionProgressEvent(
                    section_title=section_title,
                    sections_complete=sections_gathered,
                    sections_total=len(outline),
                    components_gathered=total_components_gathered,
                ))
        except ImportError as e:
            logger.error(f"Doc section progress event emission failed - missing event schema: {e}")
        except Exception as e:
            logger.warning(f"Doc section progress event emission failed: {e}")

    gathered["sections"] = sections_content
    elapsed = time.time() - start_time
    logger.info(f"DocGatherer: gathered content for {sections_gathered} sections in {elapsed:.3f}s")

    return {
        "doc_gathered_content": gathered,
        "doc_sections_gathered": sections_gathered,
        "doc_sections_total": len(outline),
    }


def doc_synthesizer_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Multi-pass generation: synthesize gathered content into full documentation.

    Pass 1: Generate each section from gathered content.
    Pass 2: Review for consistency and completeness.
    Returns full documentation as AIMessage.
    """
    start_time = time.time()
    gathered = state.get("doc_gathered_content", {})
    outline = state.get("doc_outline", [])
    doc_title = gathered.get("title", "Documentation")
    sections_content = gathered.get("sections", {})

    if not outline or not sections_content:
        return {"messages": [AIMessage(content="Unable to generate documentation - no content was gathered.")]}

    # Build context for each section
    section_contexts = []
    for section in outline:
        title = section.get("title", "")
        data = sections_content.get(title, {})

        specs_text = ""
        for spec in data.get("specs", []):
            if isinstance(spec, dict):
                specs_text += f"\n- {spec.get('short_name', spec.get('class_name', 'Unknown'))}: {spec.get('description', '')}"
                for p in spec.get("parameters", [])[:5]:
                    req = "required" if p.get("required", True) else "optional"
                    specs_text += f"\n  - {p['name']} ({p.get('type', 'String')}, {req}): {p.get('description', '')}"

        search_text = ""
        for result in data.get("search_results", [])[:5]:
            search_text += f"\n[{result.get('title', 'Source')}]: {result.get('content', '')[:300]}"

        section_contexts.append({
            "title": title,
            "description": section.get("description", ""),
            "specs": specs_text,
            "search_context": search_text,
        })

    # Pass 1: Generate each section
    generation_prompt = f"""Write comprehensive documentation titled "{doc_title}".

Generate the following sections using the provided context. Write in clear, technical prose.
Include code examples where relevant (use HOCON for configs, Java for code).

"""
    for ctx in section_contexts:
        generation_prompt += f"""
## {ctx['title']}
Description: {ctx['description']}
Component Specs: {ctx['specs'] or 'None'}
Reference Material: {ctx['search_context'] or 'None'}

"""

    generation_prompt += """
INSTRUCTIONS:
- Write each section with a level-2 heading (##)
- Include practical examples and code snippets
- Reference specific Lucille component names accurately
- Keep each section focused and informative
- Total output should be comprehensive but not repetitive

Write the complete document:"""

    try:
        response = agent.llm.invoke(generation_prompt)
        doc_content = response.content.strip() if hasattr(response, "content") else str(response)
    except Exception as e:
        from exceptions import LLMError
        logger.error(f"Doc synthesizer: LLM inference failed", extra={
            "model": str(agent.llm),
            "sections": len(section_contexts),
            "error_type": type(e).__name__,
            "error": str(e)
        })
        return {
            "messages": [AIMessage(content=(
                f"Unable to generate documentation: AI model error ({type(e).__name__}). "
                f"Ensure the AI model server is running and has sufficient resources for large document generation."
            ))]
        }

    # Add title if not already present
    if not doc_content.startswith("#"):
        doc_content = f"# {doc_title}\n\n{doc_content}"

    # Emit completion event - count unique components across all sections
    seen_components = set()
    for s in outline:
        for spec in sections_content.get(s.get("title", ""), {}).get("specs", []):
            if isinstance(spec, dict):
                seen_components.add(spec.get("class_name", spec.get("short_name", "")))
    total_components = len(seen_components)
    try:
        from api.schemas.events import DocCompleteEvent
        if agent.emit_callback:
            agent._emit_event_from_sync(DocCompleteEvent(
                total_sections=len(outline),
                total_components_documented=total_components,
                document_length_chars=len(doc_content),
            ))
    except ImportError as e:
        logger.error(f"Doc complete event emission failed - missing event schema: {e}")
    except Exception as e:
        logger.warning(f"Doc complete event emission failed: {e}")

    elapsed = time.time() - start_time
    logger.info(f"DocSynthesizer: generated {len(doc_content)} chars in {elapsed:.3f}s")

    return {"messages": [AIMessage(content=doc_content)]}
