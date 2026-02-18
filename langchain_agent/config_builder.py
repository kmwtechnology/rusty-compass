"""
Config Builder nodes for generating Lucille HOCON pipeline configurations.

Provides three LangGraph nodes:
1. config_resolver_node - Parses user request into needed components, resolves specs
2. config_generator_node - Generates valid HOCON config from resolved specs
3. config_response_node - Formats config with validation notes as AIMessage
"""

import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent_state import CustomAgentState

logger = logging.getLogger(__name__)


class ConfigResolution(BaseModel):
    connectors: list[str] = []
    stages: list[str] = []
    indexers: list[str] = []
    description: str = ""


def config_resolver_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Parse user request into needed components and resolve their specs.

    Uses the lightweight LLM to identify which Lucille components are needed,
    then looks up their structured specs from the vector store.

    Falls back to hybrid_search() if exact spec not found.

    Handles special cases:
    - "sample" / "example" requests: Generates a sample pipeline
    """
    start_time = time.time()
    messages = state["messages"]

    user_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and hasattr(msg, "content"):
            user_query = str(msg.content)
            break

    if not user_query:
        return {"config_components": [], "config_validation_notes": ["No user query found"]}

    # Detect if user is asking for a sample or example
    query_lower = user_query.lower()
    is_sample_request = any(word in query_lower for word in ["sample", "example", "template", "default"])

    if is_sample_request:
        # Return sample components for demonstration
        logger.info(f"Detected sample request: {user_query}")
        sample_components = [
            {
                "name": "CSVConnector",
                "type": "connector",
                "spec": {
                    "class_name": "com.kmwtech.lucille.connector.csv.CSVConnector",
                    "description": "Reads CSV files from a specified path",
                    "parameters": [
                        {"name": "path", "type": "String", "required": True, "description": "Path to CSV file"},
                        {"name": "encoding", "type": "String", "required": False, "default": "UTF-8", "description": "File encoding"}
                    ]
                },
                "resolved": True,
            },
            {
                "name": "CopyFields",
                "type": "stage",
                "spec": {
                    "class_name": "com.kmwtech.lucille.stage.CopyFields",
                    "description": "Copies field values in documents",
                    "parameters": [
                        {"name": "fields", "type": "Map", "required": True, "description": "Source to destination field mapping"}
                    ]
                },
                "resolved": True,
            },
            {
                "name": "OpenSearchIndexer",
                "type": "indexer",
                "spec": {
                    "class_name": "com.kmwtech.lucille.indexer.opensearch.OpenSearchIndexer",
                    "description": "Indexes documents into OpenSearch",
                    "parameters": [
                        {"name": "hosts", "type": "String[]", "required": True, "description": "OpenSearch cluster hosts"},
                        {"name": "index", "type": "String", "required": True, "description": "Index name"}
                    ]
                },
                "resolved": True,
            }
        ]
        validation_notes = ["Sample pipeline using CSV input, field transformation, and OpenSearch output"]

        elapsed = time.time() - start_time
        logger.info(f"ConfigResolver: generated {len(sample_components)} sample components in {elapsed:.3f}s")

        return {
            "config_components": sample_components,
            "config_validation_notes": validation_notes,
            "agent_mode": "config_builder",
        }

    # Use LLM to parse the request into component needs
    parse_prompt = f"""Analyze this Lucille pipeline configuration request and identify the components needed.

USER REQUEST: "{user_query}"

Return ONLY valid JSON with this structure:
{{
  "connectors": ["ConnectorClassName1"],
  "stages": ["StageClassName1", "StageClassName2"],
  "indexers": ["IndexerClassName1"],
  "description": "Brief description of what this pipeline does"
}}

Use actual Lucille class names when possible (e.g. CSVConnector, OpenSearchIndexer, CopyFields).
If the user mentions a generic concept (e.g. "CSV input"), map it to the closest Lucille class.
If unsure, include your best guess and note it.

JSON only:"""

    evaluator_llm = agent.alpha_estimator_llm or agent.llm
    components_requested = []
    pipeline_description = ""

    try:
        structured_llm = evaluator_llm.with_structured_output(ConfigResolution)
        result = structured_llm.invoke(parse_prompt)

        for comp_type in ["connectors", "stages", "indexers"]:
            for name in getattr(result, comp_type, []):
                components_requested.append({"name": name, "type": comp_type.rstrip("s")})

        pipeline_description = result.description

    except Exception as e:
        logger.error(f"Config resolver: LLM inference failed", extra={
            "model": str(evaluator_llm),
            "error_type": type(e).__name__,
            "error": str(e)
        })
        return {
            "config_components": [],
            "config_validation_notes": [
                f"AI model error: {type(e).__name__}",
                "Ensure the AI model server is running and accessible.",
                "Check logs for details.",
            ],
        }

    # Resolve each component's spec from the vector store
    resolved_components = []
    not_found = []

    for comp in components_requested:
        name = comp["name"]
        spec = agent.vector_store.get_component_spec(name)
        if spec:
            resolved_components.append({
                "name": name,
                "type": comp["type"],
                "spec": spec,
                "resolved": True,
            })
        else:
            # Fallback: search for it
            search_results = agent.vector_store.hybrid_search(
                f"Lucille {comp['type']} {name}",
                k=3, fetch_k=10, alpha=0.3
            )
            if search_results:
                resolved_components.append({
                    "name": name,
                    "type": comp["type"],
                    "spec": None,
                    "resolved": False,
                    "search_context": search_results[0].page_content[:500],
                })
            else:
                not_found.append(name)

    validation_notes = []
    if not_found:
        validation_notes.append(f"Components not found in docs: {', '.join(not_found)}")
    for comp in resolved_components:
        if not comp.get("resolved"):
            validation_notes.append(f"{comp['name']}: no structured spec found, using search context")

    # Emit config builder event
    try:
        from api.schemas.events import ConfigBuilderStartEvent, ComponentSpecRetrievalEvent, ResolvedComponent
        if agent.emit_callback:
            agent._emit_event_from_sync(ConfigBuilderStartEvent(user_request=user_query))

            component_details = []
            for comp in resolved_components:
                spec = comp.get("spec") or {}
                component_details.append(ResolvedComponent(
                    name=comp["name"],
                    component_type=comp["type"],
                    resolved=comp.get("resolved", False),
                    class_name=spec.get("class_name"),
                    description=spec.get("description"),
                ))

            agent._emit_event_from_sync(ComponentSpecRetrievalEvent(
                pipeline_description=pipeline_description,
                components_requested=[c["name"] for c in components_requested],
                components_found=[c["name"] for c in resolved_components if c.get("resolved")],
                components_not_found=not_found,
                component_details=component_details,
            ))
    except ImportError as e:
        logger.error(f"Config builder event emission failed - missing event schema: {e}")
    except Exception as e:
        logger.warning(f"Config builder event emission failed: {e}")

    elapsed = time.time() - start_time
    logger.info(f"ConfigResolver: resolved {len(resolved_components)} components in {elapsed:.3f}s")

    return {
        "config_components": resolved_components,
        "config_validation_notes": validation_notes,
        "agent_mode": "config_builder",
    }


def config_generator_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Generate a valid Lucille HOCON pipeline configuration from resolved specs.
    """
    start_time = time.time()
    components = state.get("config_components", [])
    validation_notes = state.get("config_validation_notes", [])

    if not components:
        # When no components are found, provide helpful guidance
        help_message = """# Unable to Generate Configuration

I couldn't identify specific Lucille components from your request.

To generate a pipeline configuration, please either:
1. Ask for a **sample** configuration (e.g., "Show a sample config file")
2. Mention specific components you want to use (e.g., "CSV input with OpenSearch output")
3. Describe your data flow (e.g., "Read CSV, transform fields, index to OpenSearch")

**Available Component Types:**
- **Connectors**: CSVConnector, FileConnector, DatabaseConnector, HTTPConnector
- **Stages**: CopyFields, RenameFields, SplitText, AddFields, FilterDocuments
- **Indexers**: OpenSearchIndexer, ElasticsearchIndexer, FileIndexer, PrintIndexer

Try asking again with a specific component or request a sample configuration."""

        return {
            "config_output": help_message,
            "config_validation_notes": validation_notes + ["No components identified - ask for a sample or specify components"],
        }

    # Build context from resolved specs
    spec_context_parts = []
    for comp in components:
        name = comp["name"]
        comp_type = comp["type"]
        spec = comp.get("spec")

        if spec:
            params_desc = ""
            for p in spec.get("parameters", []):
                req = "required" if p.get("required", True) else "optional"
                default = f", default={p['default']}" if p.get("default") else ""
                params_desc += f"\n    - {p['name']} ({p.get('type', 'String')}, {req}{default}): {p.get('description', '')}"
            spec_context_parts.append(
                f"{comp_type.upper()}: {name}\n"
                f"  Class: {spec.get('class_name', name)}\n"
                f"  Description: {spec.get('description', 'No description')}\n"
                f"  Parameters:{params_desc or ' (none documented)'}"
            )
        else:
            search_ctx = comp.get("search_context", "No documentation available")
            spec_context_parts.append(
                f"{comp_type.upper()}: {name}\n"
                f"  (No structured spec - using search context)\n"
                f"  Context: {search_ctx}"
            )

    spec_context = "\n\n".join(spec_context_parts)

    # Extract user query
    user_query = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_query = str(msg.content)
            break

    generation_prompt = f"""Generate a Lucille pipeline configuration in HOCON format.

USER REQUEST: "{user_query}"

AVAILABLE COMPONENT SPECS:
{spec_context}

LUCILLE HOCON FORMAT RULES:
1. Top-level keys: connectors, stages, indexers (each is an array)
2. Each component has: class (fully qualified Java class), name (unique identifier), and type-specific params
3. Connectors specify data source (e.g., path, url)
4. Stages process documents (field transformations, enrichments)
5. Indexers write to destinations (e.g., OpenSearch)
6. Use double-quoted strings for values
7. Pipeline processes: connector → stages (in order) → indexer

Generate a complete, valid HOCON config. Include comments explaining each section.
Output ONLY the HOCON configuration, no markdown fencing:"""

    try:
        response = agent.llm.invoke(generation_prompt)
        config_output = response.content.strip()

        # Clean up any markdown code fencing the LLM might add despite instructions
        # Models sometimes add ```hocon fences for readability even when told not to
        if config_output.startswith("```"):
            lines = config_output.split("\n")
            # Remove first and last lines if they're fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            config_output = "\n".join(lines)

    except Exception as e:
        from exceptions import LLMError
        logger.error(f"Config generator: LLM inference failed", extra={
            "model": str(agent.llm),
            "prompt_len": len(generation_prompt),
            "error_type": type(e).__name__,
            "error": str(e)
        })
        config_output = "# Configuration generation failed\n# Error: AI model inference failed"
        validation_notes = validation_notes + [
            f"Config generation failed: {type(e).__name__}",
            "Ensure the AI model server (Ollama) is running and has sufficient resources.",
            "Try a simpler pipeline configuration or restart the model server.",
        ]

    elapsed = time.time() - start_time
    logger.info(f"ConfigGenerator: generated config in {elapsed:.3f}s")

    return {
        "config_output": config_output,
        "config_validation_notes": validation_notes,
    }


def config_response_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Format the generated config as a response with validation notes.
    """
    config_output = state.get("config_output", "")
    validation_notes = state.get("config_validation_notes", [])
    components = state.get("config_components", [])

    # Build response
    parts = []

    # Component summary
    resolved_count = sum(1 for c in components if c.get("resolved"))
    total_count = len(components)
    parts.append(f"Generated a Lucille pipeline configuration with {total_count} component(s) "
                 f"({resolved_count} with full specs).\n")

    # Config in code block
    parts.append(f"```hocon\n{config_output}\n```\n")

    # Validation notes
    if validation_notes:
        parts.append("**Notes:**")
        for note in validation_notes:
            parts.append(f"- {note}")

    # Parameter explanations for resolved components
    has_params = False
    for comp in components:
        spec = comp.get("spec")
        if spec and spec.get("parameters"):
            if not has_params:
                parts.append("\n**Parameter Reference:**")
                has_params = True
            parts.append(f"\n*{comp['name']}:*")
            for p in spec["parameters"][:5]:  # Limit to 5 params per component
                req = "required" if p.get("required", True) else "optional"
                parts.append(f"- `{p['name']}` ({p.get('type', 'String')}, {req}): {p.get('description', '')}")

    response_text = "\n".join(parts)

    # Emit config generated event
    try:
        from api.schemas.events import ConfigGeneratedEvent
        if agent.emit_callback:
            agent._emit_event_from_sync(ConfigGeneratedEvent(
                config_preview=config_output[:500],
                component_count=total_count,
                validation_notes=validation_notes,
            ))
    except ImportError as e:
        logger.error(f"Config generated event emission failed - missing event schema: {e}")
    except Exception as e:
        logger.warning(f"Config generated event emission failed: {e}")

    return {"messages": [AIMessage(content=response_text)]}
