"""
Auto-generated catalog documents for Lucille components.

Creates compact index and category catalog documents that help answer
enumeration queries like "What stages are available?" by generating
synthetic documents that list all components of each type.
"""

import logging
from typing import Dict, List, Tuple
from uuid import uuid4

from opensearchpy import OpenSearch, helpers as os_helpers
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import OPENSEARCH_INDEX_NAME
from vector_store import create_opensearch_client

logger = logging.getLogger(__name__)

LUCILLE_COLLECTION_NAME = "lucille_docs"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Component types to generate catalogs for
CATALOG_TYPES = ["stage", "connector", "indexer"]


def _query_components_by_type(component_type: str, client: OpenSearch) -> List[Dict]:
    """
    Query all components of a given type from OpenSearch.

    Uses collapse on document_id to deduplicate chunks from the same document.
    """
    from exceptions import OpenSearchError

    try:
        body = {
            "size": 1000,
            "_source": {
                "excludes": ["embedding", "chunk_text"],
            },
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"collection_id": LUCILLE_COLLECTION_NAME}},
                        {"term": {"component_type": component_type}},
                        {"term": {"doc_type": "api_reference"}},
                    ]
                }
            },
            "sort": [{"class_name": {"order": "asc"}}],
            "collapse": {"field": "document_id"},
        }

        response = client.search(index=OPENSEARCH_INDEX_NAME, body=body)
        components = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            metadata = {
                "source": src.get("source", ""),
                "title": src.get("title", ""),
                "doc_type": src.get("doc_type", ""),
                "url": src.get("url", ""),
                "collection": src.get("collection", ""),
                "component_type": src.get("component_type", ""),
                "class_name": src.get("class_name", ""),
            }
            if "component_spec" in src:
                metadata["component_spec"] = src["component_spec"]
            components.append(metadata)
        return components

    except Exception as e:
        logger.error(f"Catalog generator: Error querying {component_type}", extra={"error": str(e)})
        raise OpenSearchError(
            f"Unable to query {component_type} components",
            operation="query_components",
            index=OPENSEARCH_INDEX_NAME,
            recoverable=True,
        )


def _cleanup_old_catalogs(client: OpenSearch) -> int:
    """
    Remove previously generated catalog documents.

    Returns:
        Number of catalog documents removed
    """
    from exceptions import OpenSearchError

    try:
        response = client.delete_by_query(
            index=OPENSEARCH_INDEX_NAME,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"collection_id": LUCILLE_COLLECTION_NAME}},
                            {"term": {"doc_type": "catalog"}},
                        ]
                    }
                }
            },
            refresh=True,
        )
        return response.get("deleted", 0)

    except Exception as e:
        logger.error(f"Catalog generator: Error during cleanup", extra={"error": str(e)})
        raise OpenSearchError(
            "Unable to cleanup old catalogs",
            operation="cleanup_catalogs",
            index=OPENSEARCH_INDEX_NAME,
            recoverable=True,
        )


def _generate_compact_index(component_type: str, components: List[Dict]) -> str:
    """
    Generate a compact index document listing all components of a type.

    Produces ~900 chars to fit in a single chunk for high-relevance retrieval.
    """
    type_plural = {
        "stage": "Stages",
        "connector": "Connectors",
        "indexer": "Indexers",
    }.get(component_type, component_type.title() + "s")

    names = []
    for comp in components:
        short_name = comp.get("class_name", "").split(".")[-1]
        if short_name:
            names.append(short_name)

    names_list = ", ".join(sorted(names))
    return (
        f"Lucille Built-in {type_plural} (Complete List, {len(names)} total): "
        f"{names_list}. "
        f"These are all the {component_type}s available in the Lucille ETL framework. "
        f"Each {component_type} can be configured in a Lucille pipeline configuration file."
    )


def _generate_category_catalog(component_type: str, components: List[Dict]) -> str:
    """
    Generate a category catalog with one-line descriptions per component.
    """
    type_plural = {
        "stage": "Stages",
        "connector": "Connectors",
        "indexer": "Indexers",
    }.get(component_type, component_type.title() + "s")

    lines = [f"Lucille {type_plural} Reference Guide ({len(components)} components)\n"]

    for comp in sorted(components, key=lambda c: c.get("class_name", "")):
        short_name = comp.get("class_name", "").split(".")[-1]
        spec = comp.get("component_spec", {})
        description = ""
        if isinstance(spec, dict):
            description = spec.get("description", "")
        if not description:
            description = comp.get("title", "")

        # Truncate description to one line
        if description:
            description = description.split(".")[0].strip()
            if len(description) > 120:
                description = description[:117] + "..."

        param_count = 0
        if isinstance(spec, dict):
            param_count = len(spec.get("parameters", []))

        param_info = f" ({param_count} params)" if param_count > 0 else ""
        lines.append(f"- {short_name}{param_info}: {description}")

    return "\n".join(lines)


def _ingest_catalog_document(
    content: str,
    title: str,
    catalog_type: str,
    component_type: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    client: OpenSearch,
) -> Tuple[int, int]:
    """
    Ingest a single catalog document into OpenSearch.

    Returns:
        Tuple of (documents_created, chunks_created)
    """
    from exceptions import OpenSearchError

    if not content or len(content) < 20:
        return 0, 0

    doc_id = str(uuid4())
    base_fields = {
        "document_id": doc_id,
        "collection_id": LUCILLE_COLLECTION_NAME,
        "source": f"auto-generated/{component_type}-{catalog_type}",
        "title": title,
        "doc_type": "catalog",
        "catalog_type": catalog_type,
        "component_type": component_type,
        "collection": LUCILLE_COLLECTION_NAME,
        "url": "",
    }

    # Chunk the content
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        chunk = content[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP
        if end == len(content):
            break

    try:
        actions = []
        for chunk_idx, chunk in enumerate(chunks):
            chunk_embedding = embeddings.embed_query(chunk)
            doc = {
                **base_fields,
                "chunk_index": chunk_idx,
                "chunk_text": chunk,
                "embedding": chunk_embedding,
            }
            actions.append({
                "_index": OPENSEARCH_INDEX_NAME,
                "_id": f"{doc_id}-{chunk_idx}",
                "_source": doc,
            })

        if actions:
            success, errors = os_helpers.bulk(client, actions, refresh=False)
            if errors:
                logger.warning(f"Catalog bulk errors for '{title}': {errors}")
            return 1, len(actions)

        return 0, 0

    except Exception as e:
        logger.error(f"Catalog generator: Error ingesting '{title}'", extra={"error": str(e)})
        raise OpenSearchError(
            f"Unable to ingest catalog '{title}'",
            operation="ingest_catalog",
            index=OPENSEARCH_INDEX_NAME,
            recoverable=True,
        )


def generate_catalog_documents(
    embeddings: GoogleGenerativeAIEmbeddings,
    client: OpenSearch = None,
) -> Tuple[int, int]:
    """
    Generate and ingest catalog documents for all component types.

    Cleans up old catalogs first, then generates:
    - Compact index per type (single-chunk, for enumeration queries)
    - Category catalog per type (with descriptions, for browsing)

    Args:
        embeddings: Embeddings model for vectorizing catalog content
        client: OpenSearch client (creates one if not provided)

    Returns:
        Tuple of (total_docs_created, total_chunks_created)
    """
    from exceptions import OpenSearchError

    if client is None:
        client = create_opensearch_client()

    print("\n   📋 Generating catalog documents...")

    try:
        # Clean up old catalogs
        removed = _cleanup_old_catalogs(client)
        if removed > 0:
            print(f"      Removed {removed} old catalog chunks")
    except OpenSearchError as e:
        print(f"      ✗ Failed to cleanup old catalogs: {e.message}")
        logger.error("Catalog generation aborted due to cleanup failure")
        raise

    total_docs = 0
    total_chunks = 0

    for component_type in CATALOG_TYPES:
        try:
            components = _query_components_by_type(component_type, client)
            if not components:
                logger.info(f"Catalog generator: No {component_type} components found")
                continue

            type_plural = component_type.title() + "s"
            print(f"      Generating catalogs for {len(components)} {type_plural}...")

            # Compact index
            compact_content = _generate_compact_index(component_type, components)
            docs, chunks = _ingest_catalog_document(
                compact_content,
                f"Lucille {type_plural} - Complete List",
                "compact_index",
                component_type,
                embeddings,
                client,
            )
            total_docs += docs
            total_chunks += chunks

            # Category catalog
            catalog_content = _generate_category_catalog(component_type, components)
            docs, chunks = _ingest_catalog_document(
                catalog_content,
                f"Lucille {type_plural} Reference Guide",
                "category_catalog",
                component_type,
                embeddings,
                client,
            )
            total_docs += docs
            total_chunks += chunks

        except OpenSearchError as e:
            print(f"      ✗ Failed to generate catalog for {component_type}: {e.message}")
            logger.error(f"Catalog generation failed for {component_type}", extra={"error": str(e)})
            continue

    # Refresh to make catalogs searchable
    client.indices.refresh(index=OPENSEARCH_INDEX_NAME)

    print(f"      ✓ Generated {total_docs} catalog documents ({total_chunks} chunks)")
    return total_docs, total_chunks
