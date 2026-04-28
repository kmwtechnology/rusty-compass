"""
Config Builder nodes for generating Lucille HOCON pipeline configurations.

Provides four LangGraph nodes:
1. config_resolver_node - Parses user request into needed components, resolves specs
2. config_generator_node - Generates valid HOCON config from resolved specs
3. config_validator_node - Validates generated config via Lucille's Java validator
4. config_response_node - Formats config with validation notes as AIMessage
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent_state import CustomAgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Component Catalog (deterministic spec lookup)
# ---------------------------------------------------------------------------
_CATALOG_PATH = Path(__file__).parent / "data" / "component_catalog.json"
_COMPONENT_CATALOG: Dict[str, Dict] = {}


def _load_catalog():
    """Load the component catalog for deterministic spec resolution."""
    global _COMPONENT_CATALOG
    if _CATALOG_PATH.exists():
        try:
            with open(_CATALOG_PATH) as f:
                data = json.load(f)
            _COMPONENT_CATALOG = {
                name.lower(): spec
                for name, spec in data.get("components", {}).items()
            }
            logger.info(f"Loaded component catalog with {len(_COMPONENT_CATALOG)} components")
        except Exception as e:
            logger.warning(f"Failed to load component catalog: {e}")
    else:
        logger.warning(f"Component catalog not found at {_CATALOG_PATH}")


_load_catalog()


# ---------------------------------------------------------------------------
# Few-Shot Example Configs
# ---------------------------------------------------------------------------
_EXAMPLE_CONFIGS = {
    "csv_solr": {
        "connectors": ["FileConnector", "CSVConnector"],
        "stages": [],
        "indexers": ["SolrIndexer"],
        "description": "Simple CSV file to Solr indexing",
        "config": '''# CSV to Solr pipeline
connectors: [
  {
    class: "com.kmwllc.lucille.connector.FileConnector",
    paths: ["conf/songs.csv"],
    name: "connector1",
    pipeline: "pipeline1"
    fileHandlers: {
      csv: { }
    }
  }
]

pipelines: [
  {
    name: "pipeline1",
    stages: []
  }
]

indexer {
  type: "Solr"
}

solr {
  useCloudClient: true
  defaultCollection: "quickstart"
  url: ["http://localhost:8983/solr"]
}''',
    },
    "s3_opensearch": {
        "connectors": ["FileConnector"],
        "stages": ["TextExtractor", "ChunkText", "EmitNestedChildren", "DeleteFields"],
        "indexers": ["OpenSearchIndexer"],
        "description": "S3 files to OpenSearch with text extraction and chunking",
        "config": '''# S3 to OpenSearch pipeline with text extraction
connectors: [
 {
    name: "fileConnector",
    class: "com.kmwllc.lucille.connector.FileConnector",
    pipeline: "pipeline1",
    paths: ["s3://bucket/files"]
    paths: [${?PATH_TO_STORAGE}]
    fileOptions: {
      getFileContent: true
    }
    s3: {
      region: "us-east-1"
      region: ${?AWS_REGION}
      accessKeyId: ${?AWS_ACCESS_KEY_ID}
      secretAccessKey: ${?AWS_SECRET_ACCESS_KEY}
    }
 }
]

pipelines: [
  {
    name: "pipeline1",
    stages: [
     {
       name: "TextExtractor"
       class: "com.kmwllc.lucille.tika.stage.TextExtractor"
       byteArrayField: "file_content"
       metadataPrefix: ""
       blacklist: []
     },
     {
      name: "ChunkText"
      class: "com.kmwllc.lucille.stage.ChunkText"
      source: "text"
      dest: "text"
      chunkingMethod: "paragraph"
     },
     {
      name: "EmitNestedChildren"
      class: "com.kmwllc.lucille.stage.EmitNestedChildren"
      dropParent: "false"
     },
     {
      name: "DeleteFields"
      class: "com.kmwllc.lucille.stage.DeleteFields"
      fields: ["file_content", "_version"]
     }
    ]
  }
]

indexer {
  type: "OpenSearch"
  batchTimeout: 1000
  batchSize: 100
  sendEnabled: true
}

opensearch {
  url: "http://localhost:9200"
  url: ${?OPENSEARCH_URL}
  index: "s3-docs"
  index: ${?OPENSEARCH_INDEX}
  acceptInvalidCert: true
}''',
    },
    "opensearch_ingest": {
        "connectors": ["FileConnector"],
        "stages": ["TextExtractor", "RenameFields", "DeleteFields"],
        "indexers": ["OpenSearchIndexer"],
        "description": "File ingest to OpenSearch with text extraction and field renaming",
        "config": '''# File ingest to OpenSearch with text extraction
connectors: [
  {
    name: "fileConnector",
    class: "com.kmwllc.lucille.connector.FileConnector",
    pipeline: "pipeline1",
    paths: ["/data/files"]
    paths: [${?PATH_TO_FILES}]
  },
]

pipelines: [
  {
    name: "pipeline1",
    stages: [
     {
       name: "TextExtractor"
       class: "com.kmwllc.lucille.tika.stage.TextExtractor"
       byteArrayField: "file_content"
       metadataPrefix: ""
       blacklist: []
     },
     {
       name: "renameFields",
       class: "com.kmwllc.lucille.stage.RenameFields"
       fieldMapping: {
         "text": "body",
         "_dc_subject": "subject"
       }
       updateMode: "overwrite"
     },
     {
       name: "deleteFields"
       class: "com.kmwllc.lucille.stage.DeleteFields"
       fields: ["file_content"]
     }
    ]
  }
]

indexer {
  type: "OpenSearch"
  batchTimeout: 1000
  batchSize: 2000
  sendEnabled: true
}

opensearch {
  url: "http://localhost:9200"
  url: ${?OPENSEARCH_URL}
  index: "documents"
  index: ${?OPENSEARCH_INDEX}
  acceptInvalidCert: true
}''',
    },
    "csv_to_csv": {
        "connectors": ["FileConnector", "CSVConnector"],
        "stages": ["RenameFields", "CopyFields"],
        "indexers": ["CSVIndexer"],
        "description": "CSV input with field transformations to CSV output",
        "config": '''# CSV to CSV transformation pipeline
connectors: [
  {
    name: "csvConnector",
    class: "com.kmwllc.lucille.connector.FileConnector",
    pipeline: "pipeline1",
    paths: ["data/input.csv"],
    fileHandlers: {
      csv: { }
    }
  }
]

pipelines: [
  {
    name: "pipeline1",
    stages: [
      {
        name: "renameFields",
        class: "com.kmwllc.lucille.stage.RenameFields",
        fieldMapping: {
          "old_name": "new_name"
        }
      }
    ]
  }
]

indexer {
  type: "CSV"
  outputFile: "data/output.csv"
}''',
    },
    "db_opensearch": {
        "connectors": ["DatabaseConnector"],
        "stages": ["CopyFields", "Concatenate"],
        "indexers": ["OpenSearchIndexer"],
        "description": "Database to OpenSearch with field transformations",
        "config": '''# Database to OpenSearch pipeline
connectors: [
  {
    name: "dbConnector",
    class: "com.kmwllc.lucille.connector.jdbc.DatabaseConnector",
    pipeline: "pipeline1",
    driver: "org.postgresql.Driver",
    connectionString: "jdbc:postgresql://localhost:5432/mydb"
    connectionString: ${?DB_CONNECTION_STRING}
    jdbcUser: "user"
    jdbcUser: ${?DB_USER}
    jdbcPassword: "password"
    jdbcPassword: ${?DB_PASSWORD}
    sql: "SELECT id, title, body, category FROM documents"
  }
]

pipelines: [
  {
    name: "pipeline1",
    stages: [
      {
        name: "copyCategory",
        class: "com.kmwllc.lucille.stage.CopyFields",
        fieldMapping: {
          "category": "category_facet"
        }
      },
      {
        name: "buildSummary",
        class: "com.kmwllc.lucille.stage.Concatenate",
        dest: "summary",
        formatString: "{title}: {body}"
      }
    ]
  }
]

indexer {
  type: "OpenSearch"
  batchTimeout: 1000
  batchSize: 500
  sendEnabled: true
}

opensearch {
  url: "http://localhost:9200"
  url: ${?OPENSEARCH_URL}
  index: "db-documents"
  index: ${?OPENSEARCH_INDEX}
  acceptInvalidCert: true
}''',
    },
}


def _select_examples(components: List[dict], max_examples: int = 2) -> List[str]:
    """Select best-matching example configs based on component overlap."""
    requested_names = {c["name"].lower() for c in components}
    requested_types = {c["type"] for c in components}

    scored = []
    for key, example in _EXAMPLE_CONFIGS.items():
        example_names = {n.lower() for n in
            example.get("connectors", []) + example.get("stages", []) + example.get("indexers", [])}

        name_overlap = len(requested_names & example_names)
        type_overlap = 0
        if "connector" in requested_types and example.get("connectors"):
            type_overlap += 1
        if "indexer" in requested_types and example.get("indexers"):
            type_overlap += 1

        scored.append((name_overlap * 3 + type_overlap, key, example))

    scored.sort(reverse=True, key=lambda x: x[0])
    return [s[2]["config"] for s in scored[:max_examples]]


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

You MUST use exact Lucille class names from this list:

CONNECTORS: {', '.join(s['short_name'] for s in _COMPONENT_CATALOG.values() if s.get('component_type') == 'connector')}
STAGES: {', '.join(s['short_name'] for s in _COMPONENT_CATALOG.values() if s.get('component_type') == 'stage')}
INDEXERS: {', '.join(s['short_name'] for s in _COMPONENT_CATALOG.values() if s.get('component_type') == 'indexer')}

Important: For S3/Azure/GCP file ingestion, use FileConnector (it supports cloud storage via config options).
Map the user's description to the closest class name from the lists above.

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

    # Resolve each component's spec — catalog first, then vector store fallback
    resolved_components = []
    not_found = []

    for comp in components_requested:
        name = comp["name"]

        # 1. Try deterministic catalog lookup (case-insensitive)
        catalog_entry = _COMPONENT_CATALOG.get(name.lower())
        if catalog_entry:
            resolved_components.append({
                "name": name,
                "type": comp["type"],
                "spec": catalog_entry,
                "resolved": True,
                "resolution_source": "catalog",
            })
            continue

        # 2. Fall back to vector store
        spec = agent.vector_store.get_component_spec(name)
        if spec:
            resolved_components.append({
                "name": name,
                "type": comp["type"],
                "spec": spec,
                "resolved": True,
                "resolution_source": "vector_store",
            })
            continue

        # 3. Final fallback: hybrid search for raw text context
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

    # Select matching example configs for few-shot context
    examples = _select_examples(components)
    examples_section = ""
    if examples:
        examples_section = "\nREFERENCE EXAMPLES (use these as templates for format and structure):\n"
        for i, ex in enumerate(examples, 1):
            examples_section += f"\n--- Example {i} ---\n{ex}\n--- End Example {i} ---\n"

    # Check if this is a retry (validation errors from previous attempt)
    previous_config = state.get("config_output")
    validation_errors = state.get("config_validation_errors")
    validation_attempts = state.get("config_validation_attempts", 0)

    if validation_errors and previous_config and validation_attempts > 0:
        # Build retry prompt with error context
        error_lines = []
        for component, errors in validation_errors.items():
            for error in errors:
                error_lines.append(f"  - {component}: {error}")
        errors_text = "\n".join(error_lines)

        generation_prompt = f"""Fix the following Lucille pipeline configuration that failed validation.

PREVIOUS CONFIG (with errors):
{previous_config}

VALIDATION ERRORS:
{errors_text}

AVAILABLE COMPONENT SPECS:
{spec_context}
{examples_section}
LUCILLE HOCON FORMAT RULES:
1. Top-level keys: connectors (array), pipelines (array of objects with name + stages), indexer (object with type)
2. Stages go INSIDE pipelines[].stages[], NOT at the top level
3. Each connector/stage needs: class (fully qualified Java class name), name (unique identifier)
4. Connectors must reference a pipeline by name
5. The indexer block specifies type ("OpenSearch", "Solr", "CSV", etc.) plus config
6. Indexer-specific config goes in a separate top-level block (e.g., opensearch, solr)
7. Use double-quoted strings for values
8. For optional env overrides, declare the key TWICE on separate lines — default first, then override:
     paths: ["s3://bucket/files"]
     paths: [${{?PATH_TO_STORAGE}}]
   NEVER combine them on one line. NEVER write paths: ${{?VAR}} ["default"]

Fix ALL validation errors. Common issues:
- Unknown properties: Remove properties not in the component spec
- Missing required properties: Add the required property with a placeholder value
- Unknown parents: Use the correct parent name from the spec
- Missing class: Every stage/connector must have a "class" property

Output ONLY the corrected HOCON configuration, no markdown fencing:"""
    else:
        generation_prompt = f"""Generate a Lucille pipeline configuration in HOCON format.

USER REQUEST: "{user_query}"

AVAILABLE COMPONENT SPECS:
{spec_context}
{examples_section}
LUCILLE HOCON FORMAT RULES:
1. Top-level keys: connectors (array), pipelines (array of objects with name + stages), indexer (object with type)
2. Stages go INSIDE pipelines[].stages[], NOT at the top level
3. Each connector/stage needs: class (fully qualified Java class name), name (unique identifier)
4. Connectors must reference a pipeline by name
5. The indexer block specifies type ("OpenSearch", "Solr", "CSV", etc.) plus config
6. Indexer-specific config goes in a separate top-level block (e.g., opensearch, solr)
7. Use double-quoted strings for values
8. For optional env overrides, declare the key TWICE on separate lines — default first, then override:
     paths: ["s3://bucket/files"]
     paths: [${{?PATH_TO_STORAGE}}]
   NEVER combine them on one line. NEVER write paths: ${{?VAR}} ["default"]

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


def config_validator_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Validate generated config using Lucille's Java validator.

    If validation fails and retries remain, sets errors in state for the
    generator to use on the next attempt. If validation passes or max retries
    exceeded, proceeds to config_response.
    """
    from config import ENABLE_CONFIG_VALIDATION, CONFIG_VALIDATION_MAX_RETRIES

    start_time = time.time()
    config_output = state.get("config_output", "")
    validation_attempts = state.get("config_validation_attempts", 0)
    validation_notes = list(state.get("config_validation_notes", []))

    # Skip if validation disabled or config generation failed
    if not ENABLE_CONFIG_VALIDATION:
        return {
            "config_validation_passed": True,
            "config_validation_attempts": validation_attempts,
        }

    if not config_output or config_output.startswith("# Configuration generation failed"):
        return {
            "config_validation_passed": False,
            "config_validation_attempts": validation_attempts,
        }

    # Try to validate
    try:
        from lucille_validator import (
            validate_config,
            is_validator_available,
            ValidationOutcome,
        )

        if not is_validator_available():
            logger.info("Config validator: Java validator not available, skipping")
            validation_notes.append("Validation skipped: Lucille validator not available")
            return {
                "config_validation_passed": True,
                "config_validation_notes": validation_notes,
                "config_validation_attempts": validation_attempts,
            }

        result = validate_config(config_output)
        validation_attempts += 1
        elapsed = time.time() - start_time

        # Routing decision: should we retry the generator?
        # Only when the LLM has a real chance of fixing it (config-quality
        # errors). For validator-side problems we don't burn retries.
        will_retry = result.can_retry and validation_attempts <= CONFIG_VALIDATION_MAX_RETRIES

        # Emit validation event with full outcome detail for observability.
        try:
            from api.schemas.events import ConfigValidationEvent
            if agent.emit_callback:
                agent._emit_event_from_sync(ConfigValidationEvent(
                    valid=result.valid,
                    outcome=result.outcome.value,
                    attempt=validation_attempts,
                    error_count=sum(len(v) for v in result.errors.values()),
                    errors=result.errors,
                    diagnostic=result.diagnostic,
                    will_retry=will_retry,
                ))
        except Exception as e:
            logger.debug(f"Config validation event emission skipped: {e}")

        outcome = result.outcome

        # ── Successful validation ────────────────────────────────────────
        if outcome == ValidationOutcome.VALID:
            logger.info(
                "Config validator: VALID (attempt=%d, elapsed=%.3fs)",
                validation_attempts, elapsed,
            )
            validation_notes.append(
                f"Validated by Lucille validator (attempt {validation_attempts})"
            )
            return {
                "config_validation_passed": True,
                "config_validation_errors": {},
                "config_validation_notes": validation_notes,
                "config_validation_attempts": validation_attempts,
            }

        # ── Validator-side problems (not user-fixable) ───────────────────
        # Surface the diagnostic to operators but don't block the user — the
        # config may still be correct; we just couldn't confirm it.
        if outcome in (
            ValidationOutcome.VALIDATOR_UNHEALTHY,
            ValidationOutcome.MISSING_PLUGIN,
            ValidationOutcome.TIMEOUT,
            ValidationOutcome.VALIDATOR_UNAVAILABLE,
        ):
            log_fn = logger.error if outcome == ValidationOutcome.VALIDATOR_UNHEALTHY else logger.info
            log_fn(
                "Config validator: outcome=%s diagnostic=%r (attempt=%d, elapsed=%.3fs) "
                "— validation skipped, no retry. Returning generated config as-is.",
                outcome.value, result.diagnostic, validation_attempts, elapsed,
            )
            validation_notes.append(
                f"Validation skipped ({outcome.value}): {result.diagnostic or 'no detail'}"
            )
            return {
                "config_validation_passed": True,
                "config_validation_errors": {},
                "config_validation_notes": validation_notes,
                "config_validation_attempts": validation_attempts,
            }

        # ── User-fixable errors (STRUCTURAL_ERRORS, PARSE_ERROR) ─────────
        error_summary = [
            f"{component}: {error}"
            for component, errors in result.errors.items()
            for error in errors
        ]
        logger.warning(
            "Config validator: outcome=%s error_count=%d (attempt=%d, elapsed=%.3fs)",
            outcome.value, len(error_summary), validation_attempts, elapsed,
        )
        # Per-error lines at DEBUG so operators can opt-in without log spam.
        for err_line in error_summary:
            logger.debug("  validation_err: %s", err_line)

        if will_retry:
            validation_notes.append(
                f"Validation attempt {validation_attempts} failed: "
                f"{len(error_summary)} error(s) — retrying"
            )
        else:
            validation_notes.extend(
                [
                    f"Validation failed after {validation_attempts} attempt(s)",
                    "Remaining errors:",
                ]
                + error_summary[:5]
            )

        return {
            "config_validation_passed": False,
            "config_validation_errors": result.errors,
            "config_validation_notes": validation_notes,
            "config_validation_attempts": validation_attempts,
        }

    except ImportError:
        logger.info("Config validator: lucille_validator module not available, skipping")
        return {
            "config_validation_passed": True,
            "config_validation_attempts": validation_attempts,
        }
    except Exception as e:
        # Defense-in-depth: never let a validator bug crash the graph. Surface
        # to operators via ERROR log; treat as skipped so the user still gets
        # their generated config.
        logger.exception("Config validator: unexpected error in validator node")
        validation_notes.append(f"Validation skipped (validator node error): {type(e).__name__}: {e}")
        return {
            "config_validation_passed": True,
            "config_validation_notes": validation_notes,
            "config_validation_attempts": validation_attempts,
        }


def config_response_node(state: CustomAgentState, agent) -> Dict[str, Any]:
    """
    Format the generated config as a response with validation notes.
    """
    config_output = state.get("config_output", "")
    validation_notes = state.get("config_validation_notes", [])
    components = state.get("config_components", [])

    # Prepare mode shift context for explicit feedback (Layer 3)
    mode_shift_type = state.get("mode_shift_type", "continuation")
    previous_mode = state.get("previous_agent_mode", "rag")
    if mode_shift_type == "soft_shift" and previous_mode == "config_builder":
        shift_note = "Building on the pipeline configuration from earlier — "
    elif mode_shift_type == "hard_shift":
        shift_note = "Switching to pipeline configuration — "
    else:
        shift_note = ""

    # Build response
    parts = []
    if shift_note:
        parts.append(shift_note)

    # Component summary
    resolved_count = sum(1 for c in components if c.get("resolved"))
    total_count = len(components)
    parts.append(f"Generated a Lucille pipeline configuration with {total_count} component(s) "
                 f"({resolved_count} with full specs).\n")

    # Config in code block
    parts.append(f"```hocon\n{config_output}\n```\n")

    # Validation status
    validation_passed = state.get("config_validation_passed")
    validation_attempts = state.get("config_validation_attempts", 0)

    if validation_passed is True and validation_attempts > 0:
        parts.append(f"**Validation:** Passed (verified by Lucille validator, attempt {validation_attempts})\n")
    elif validation_passed is False and validation_attempts > 0:
        parts.append(f"**Validation:** Failed after {validation_attempts} attempt(s)\n")

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
