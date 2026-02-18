#!/usr/bin/env python3
"""
Lucille Comprehensive Documentation Ingestion Script

Ingests multiple documentation sources from Lucille into the OpenSearch vector store:
- Javadoc HTML (API reference)
- Markdown documentation (architecture, guides, getting started)
- Configuration examples (HOCON files)
- Example project README files

Usage:
    python ingest_lucille_docs.py           # Ingest all documentation sources
    python ingest_lucille_docs.py --stats   # Show current stats only
    python ingest_lucille_docs.py --javadoc-only  # Only javadoc (legacy mode)
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from opensearchpy import helpers as os_helpers
from bs4 import BeautifulSoup
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import (
    EMBEDDINGS_MODEL,
    VECTOR_DIMENSION,
    OPENSEARCH_INDEX_NAME,
    LUCILLE_JAVADOC_PATH,
    LUCILLE_PROJECT_DIR,
)
from vector_store import create_opensearch_client, INDEX_MAPPING, SEARCH_PIPELINE, OPENSEARCH_SEARCH_PIPELINE

logger = logging.getLogger(__name__)

# Document chunking settings (matching setup.py)
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Collection name for Lucille docs
LUCILLE_COLLECTION_NAME = "lucille_docs"

# GitHub repository URL for Lucille framework
LUCILLE_GITHUB_URL = "https://github.com/kmwtechnology/lucille/blob/main"

# Paths for different documentation sources
LUCILLE_ROOT = Path(LUCILLE_PROJECT_DIR)
LUCILLE_MARKDOWN_DOCS = LUCILLE_ROOT / "doc" / "site" / "content" / "en" / "docs"
LUCILLE_EXAMPLES = LUCILLE_ROOT / "lucille-examples"
LUCILLE_CONFIG_FILES = [
    LUCILLE_ROOT / "application-example.conf",
    LUCILLE_ROOT / "validation-example.conf",
]
LUCILLE_README = LUCILLE_ROOT / "README.md"


def classify_component_type(source_path: str) -> str:
    """
    Classify a javadoc source path into a Lucille component type.

    Args:
        source_path: Relative path within javadoc (e.g. "com/kmwllc/lucille/stage/CopyFields.html")

    Returns:
        Component type: "stage", "connector", "indexer", "core", or "other_api"
    """
    path_lower = source_path.replace("\\", "/").lower()

    if "/stage/" in path_lower:
        return "stage"
    if "/connector/" in path_lower:
        return "connector"
    if "/indexer/" in path_lower:
        return "indexer"
    if "/core/" in path_lower:
        return "core"
    return "other_api"


def extract_fully_qualified_class_name(source_path: str) -> str:
    """
    Extract a fully-qualified Java class name from a javadoc file path.

    Args:
        source_path: Relative path like "com/kmwllc/lucille/stage/CopyFields.html"

    Returns:
        Fully-qualified class name like "com.kmwllc.lucille.stage.CopyFields"
    """
    # Remove .html extension and convert slashes to dots
    path = source_path.replace("\\", "/")
    if path.endswith(".html"):
        path = path[:-5]
    return path.replace("/", ".")


def generate_github_url(source_path: str, doc_type: str) -> str:
    """
    Generate a GitHub URL for the source document.

    For javadoc, maps to Maven Central Javadoc hosting.
    For other docs, maps to GitHub repository URLs.

    Args:
        source_path: Relative path to the source file within Lucille project
        doc_type: Type of document (api_reference, guide, example, config, readme)

    Returns:
        Full URL to the source file (Maven Central for javadoc, GitHub for others),
        or empty string if unable to generate
    """
    if not source_path:
        return ""

    try:
        relative_path = source_path.replace("\\", "/")  # Normalize Windows paths

        # For Javadoc files, map to Maven Central Javadoc (javadoc.io)
        # doc_type == "api_reference" indicates javadoc-derived documents
        if doc_type == "api_reference":
            # Extract the fully-qualified class name from the path
            # Example: "com/kmwllc/lucille/core/Connector.html" -> "com/kmwllc/lucille/core/Connector"
            # (relative_path is already relative to LUCILLE_JAVADOC_PATH, so no "apidocs/" prefix)
            class_path = relative_path.replace(".html", "")

            # Use javadoc.io for Maven Central Javadoc hosting
            # Most Lucille API classes are published in lucille-core
            # Pattern: https://javadoc.io/doc/groupId/artifactId/version/class-path.html
            # Using "latest" allows javadoc.io to serve the latest published version
            return f"https://javadoc.io/doc/com.kmwllc/lucille-core/latest/{class_path}.html"

        # For Markdown documentation
        if doc_type in ("guide", "tutorial", "readme"):
            return f"{LUCILLE_GITHUB_URL}/{relative_path}"

        # For example projects and config files
        if doc_type in ("example", "config"):
            return f"{LUCILLE_GITHUB_URL}/{relative_path}"

        # Default fallback
        return f"{LUCILLE_GITHUB_URL}/{relative_path}"
    except Exception:
        return ""


def extract_javadoc_content(html_content: str) -> str:
    """
    Extract meaningful documentation content from javadoc HTML.

    Focuses on:
    - Class descriptions (.block in .class-description)
    - Method descriptions (.detail sections with .block)
    - Parameter/return/throws documentation (.notes sections)

    Filters out:
    - Navigation elements
    - JavaScript warnings
    - Table headers
    - Inherited method lists
    - Section labels
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Remove noise elements
    for selector in ['script', 'style', 'nav', 'header', 'footer', 'noscript']:
        for element in soup.find_all(selector):
            element.decompose()

    # Remove search boxes and navigation (not flex-box as it may contain main content)
    for element in soup.find_all(class_=['top-nav', 'sub-nav', 'search']):
        element.decompose()

    content_parts = []

    # Extract main content area
    main_content = soup.find('main', role='main')
    if not main_content:
        main_content = soup.find('div', class_='content-container')

    if main_content:
        # Extract class description
        class_desc = main_content.find('section', class_='class-description')
        if class_desc:
            # Get the main description block
            desc_block = class_desc.find('div', class_='block')
            if desc_block:
                content_parts.append(f"Class Description: {desc_block.get_text(separator=' ', strip=True)}")

        # Extract field, constructor, and method details
        for detail_section in main_content.find_all('section', class_='detail'):
            # Get section heading (field/constructor/method name)
            heading = detail_section.find(['h3', 'h4'])
            section_name = heading.get_text(strip=True) if heading else ""

            # Get description block
            desc_block = detail_section.find('div', class_='block')
            if desc_block:
                description = desc_block.get_text(separator=' ', strip=True)
                content_parts.append(f"{section_name}: {description}")

            # Get parameter/return/throws documentation
            notes = detail_section.find('dl', class_='notes')
            if notes:
                notes_text = []
                dts = notes.find_all('dt')
                dds = notes.find_all('dd')
                for dt, dd in zip(dts, dds):
                    label = dt.get_text(strip=True)
                    value = dd.get_text(separator=' ', strip=True)
                    # Skip "Description copied from" entries
                    if not label.startswith('Description copied from'):
                        notes_text.append(f"{label}: {value}")
                if notes_text:
                    content_parts.append(' '.join(notes_text))

    # Join all parts and clean up whitespace
    full_content = '\n\n'.join(content_parts)

    # Final cleanup
    full_content = re.sub(r'\s+', ' ', full_content)  # Normalize whitespace
    full_content = re.sub(r'\n\s*\n', '\n\n', full_content)  # Remove excessive newlines

    return full_content.strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]

        if chunk.strip():
            chunks.append(chunk)

        start = end - overlap
        if end == len(text):
            break

    return chunks


def extract_class_name(html_path: Path) -> str:
    """Extract class name from javadoc HTML file path."""
    # Convert path like "com/kmwllc/lucille/ClassName.html" to "ClassName"
    return html_path.stem.replace("_", " ").title()


def parse_markdown(content: str) -> str:
    """Parse markdown, extracting title and content."""
    # Remove markdown syntax but preserve structure
    # Remove code blocks first (preserve content but mark differently)
    content = re.sub(r'```[\s\S]*?```', '[CODE BLOCK]', content)

    # Remove inline code formatting
    content = re.sub(r'`([^`]+)`', r'\1', content)

    # Remove bold/italic markers
    content = re.sub(r'\*\*([^\*]+)\*\*', r'\1', content)
    content = re.sub(r'\*([^\*]+)\*', r'\1', content)
    content = re.sub(r'__([^_]+)__', r'\1', content)
    content = re.sub(r'_([^_]+)_', r'\1', content)

    # Remove heading markers but keep the text
    content = re.sub(r'^#+\s+', '', content, flags=re.MULTILINE)

    # Remove links but keep text
    content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)

    # Remove images
    content = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', content)

    # Remove horizontal rules
    content = re.sub(r'^(-{3,}|_{3,}|\*{3,})$', '', content, flags=re.MULTILINE)

    # Clean up whitespace
    content = re.sub(r'\s+', ' ', content)
    return content.strip()


def get_markdown_title(filepath: Path) -> str:
    """Extract title from markdown file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                # Look for first heading
                if line.startswith('#'):
                    return line.lstrip('#').strip()
                # Or use filename if no heading found
                if line.strip():
                    return filepath.stem.replace('_', ' ').replace('-', ' ').title()
    except Exception:
        pass
    return filepath.stem.replace('_', ' ').replace('-', ' ').title()


def find_javadoc_files() -> List[Path]:
    """Find all class HTML files in javadoc."""
    if not LUCILLE_JAVADOC_PATH.exists():
        logger.error(f"Lucille javadoc path not found: {LUCILLE_JAVADOC_PATH}")
        return []

    html_files = list(LUCILLE_JAVADOC_PATH.rglob("*.html"))
    # Filter out navigation and index pages
    class_files = [
        f for f in html_files
        if f.name not in ("index.html", "overview-summary.html", "package-summary.html", "module-summary.html")
        and not f.name.startswith("allclasses")
        and not f.name.startswith("constant-values")
        and not f.name.startswith("deprecated")
        and not f.name.startswith("overview-")
        and not f.name.startswith("help-")
        and not f.name.startswith("index-all")
        and "com/kmwllc" in str(f)  # Only Lucille classes, not Java standard library
    ]
    return sorted(class_files)


def find_markdown_docs() -> List[Path]:
    """Find all markdown documentation files."""
    if not LUCILLE_MARKDOWN_DOCS.exists():
        return []

    md_files = list(LUCILLE_MARKDOWN_DOCS.rglob("*.md"))
    return sorted(md_files)


def find_example_readmes() -> List[Path]:
    """Find README files in example projects."""
    if not LUCILLE_EXAMPLES.exists():
        return []

    readmes = list(LUCILLE_EXAMPLES.rglob("README.md"))
    return sorted(readmes)


def find_config_files() -> List[Path]:
    """Find configuration example files."""
    existing = [f for f in LUCILLE_CONFIG_FILES if f.exists()]
    return sorted(existing)


def ensure_index_exists(client):
    """Create the OpenSearch index and search pipeline if they don't exist."""
    try:
        if not client.indices.exists(index=OPENSEARCH_INDEX_NAME):
            client.indices.create(index=OPENSEARCH_INDEX_NAME, body=INDEX_MAPPING)
            logger.info(f"Created index '{OPENSEARCH_INDEX_NAME}'")
        else:
            logger.info(f"Index '{OPENSEARCH_INDEX_NAME}' already exists")

        # Create search pipeline
        try:
            client.transport.perform_request(
                "PUT",
                f"/_search/pipeline/{OPENSEARCH_SEARCH_PIPELINE}",
                body=SEARCH_PIPELINE,
            )
            logger.info(f"Search pipeline '{OPENSEARCH_SEARCH_PIPELINE}' created/updated")
        except Exception as e:
            logger.warning(f"Could not create search pipeline: {e}")

    except Exception as e:
        logger.error(f"Error ensuring index exists: {e}")
        raise


def ingest_document(
    doc_id: str,
    content: str,
    title: str,
    source: str,
    doc_type: str,
    embeddings: GoogleGenerativeAIEmbeddings,
    extra_metadata: Optional[Dict] = None,
    client=None,
) -> Tuple[int, int]:
    """
    Ingest a single document into OpenSearch.

    Each chunk becomes a standalone OpenSearch document with flat metadata.

    Args:
        doc_id: Unique document ID
        content: Full document content
        title: Document title
        source: Source file path
        doc_type: Type of document (api_reference, guide, example, config, etc.)
        embeddings: Embeddings model instance
        extra_metadata: Additional metadata to merge (e.g. component_type, class_name, component_spec)
        client: OpenSearch client instance

    Returns:
        Tuple of (docs_inserted, chunks_inserted)
    """
    if not content or len(content) < 50:
        return 0, 0

    github_url = generate_github_url(source, doc_type)

    base_fields = {
        "document_id": doc_id,
        "collection_id": LUCILLE_COLLECTION_NAME,
        "source": source,
        "title": title,
        "doc_type": doc_type,
        "collection": LUCILLE_COLLECTION_NAME,
        "url": github_url,
    }

    # Merge extra metadata as top-level fields
    if extra_metadata:
        for key in ("component_type", "class_name", "component_spec"):
            if key in extra_metadata:
                base_fields[key] = extra_metadata[key]

    try:
        chunks = chunk_text(content)
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

        if actions and client:
            success, errors = os_helpers.bulk(client, actions, refresh=False)
            if errors:
                logger.warning(f"Bulk ingestion errors for '{title}': {errors}")
            return 1, len(actions)

        return 0, 0
    except Exception as e:
        logger.warning(f"Error ingesting document '{title}': {e}")
        return 0, 0


def ingest_javadoc_files(embeddings: GoogleGenerativeAIEmbeddings) -> Tuple[int, int]:
    """Ingest Javadoc HTML files."""
    print("\n   📖 Ingesting Javadoc API documentation...")

    html_files = find_javadoc_files()
    if not html_files:
        print(f"      ⚠ No javadoc files found")
        return 0, 0

    print(f"      Found {len(html_files)} javadoc files")
    total_docs = 0
    total_chunks = 0

    for i, html_file in enumerate(html_files, 1):
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()

            content = extract_javadoc_content(html_content)

            title = extract_class_name(html_file)
            relative_path = html_file.relative_to(LUCILLE_JAVADOC_PATH)
            relative_path_str = str(relative_path)

            # Classify component type and extract fully-qualified class name
            component_type = classify_component_type(relative_path_str)
            class_name = extract_fully_qualified_class_name(relative_path_str)

            # Contextual prefix - makes individual docs rank higher for enumeration queries
            if component_type in ("stage", "connector", "indexer"):
                content = f"Lucille built-in {component_type}: {title}\n\n{content}"

            # Extract structured component spec from javadoc content
            extra_meta: Dict = {
                "component_type": component_type,
                "class_name": class_name,
            }

            try:
                from component_specs import extract_component_spec
                spec = extract_component_spec(content, relative_path_str)
                if spec:
                    extra_meta["component_spec"] = spec.to_dict()
            except ImportError:
                pass  # component_specs module not yet available

            docs, chunks = ingest_document(
                str(uuid4()),
                content,
                title,
                relative_path_str,
                "api_reference",
                embeddings,
                extra_metadata=extra_meta,
                client=_get_client(),
            )
            total_docs += docs
            total_chunks += chunks

            if i % 10 == 0:
                print(f"      Processed {i}/{len(html_files)} javadoc files...")

        except Exception as e:
            logger.warning(f"Error processing javadoc {html_file}: {e}")
            continue

    print(f"      ✓ Ingested {total_docs} javadoc documents ({total_chunks} chunks)")
    return total_docs, total_chunks


def ingest_markdown_docs(embeddings: GoogleGenerativeAIEmbeddings) -> Tuple[int, int]:
    """Ingest Markdown documentation files."""
    print("\n   📘 Ingesting Markdown guides and architecture docs...")

    md_files = find_markdown_docs()
    if not md_files:
        print(f"      ⚠ No markdown docs found")
        return 0, 0

    print(f"      Found {len(md_files)} markdown files")
    total_docs = 0
    total_chunks = 0

    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                raw_content = f.read()

            content = parse_markdown(raw_content)
            title = get_markdown_title(md_file)
            relative_path = md_file.relative_to(LUCILLE_ROOT)

            # Determine doc type from path
            doc_type = "guide"
            if "architecture" in str(relative_path):
                doc_type = "architecture"
            elif "getting-started" in str(relative_path):
                doc_type = "getting_started"
            elif "contributing" in str(relative_path):
                doc_type = "contributing"
            elif "prod" in str(relative_path):
                doc_type = "production"

            docs, chunks = ingest_document(
                str(uuid4()),
                content,
                title,
                str(relative_path),
                doc_type,
                embeddings,
                client=_get_client(),
            )
            total_docs += docs
            total_chunks += chunks

        except Exception as e:
            logger.warning(f"Error processing markdown {md_file}: {e}")
            continue

    print(f"      ✓ Ingested {total_docs} markdown documents ({total_chunks} chunks)")
    return total_docs, total_chunks


def ingest_config_examples(embeddings: GoogleGenerativeAIEmbeddings) -> Tuple[int, int]:
    """Ingest configuration example files."""
    print("\n   ⚙️  Ingesting configuration examples...")

    config_files = find_config_files()
    if not config_files:
        print(f"      ⚠ No config files found")
        return 0, 0

    print(f"      Found {len(config_files)} config files")
    total_docs = 0
    total_chunks = 0

    for config_file in config_files:
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Clean HOCON comments
            content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'/\*[\s\S]*?\*/', '', content)
            content = re.sub(r'\s+', ' ', content)

            title = f"Configuration Example: {config_file.stem}"
            relative_path = config_file.relative_to(LUCILLE_ROOT)

            docs, chunks = ingest_document(
                str(uuid4()),
                content,
                title,
                str(relative_path),
                "config_example",
                embeddings,
                client=_get_client(),
            )
            total_docs += docs
            total_chunks += chunks

        except Exception as e:
            logger.warning(f"Error processing config {config_file}: {e}")
            continue

    print(f"      ✓ Ingested {total_docs} config examples ({total_chunks} chunks)")
    return total_docs, total_chunks


def ingest_example_readmes(embeddings: GoogleGenerativeAIEmbeddings) -> Tuple[int, int]:
    """Ingest README files from example projects."""
    print("\n   🎯 Ingesting example project guides...")

    readmes = find_example_readmes()
    if not readmes:
        print(f"      ⚠ No example READMEs found")
        return 0, 0

    print(f"      Found {len(readmes)} example projects")
    total_docs = 0
    total_chunks = 0

    for readme_file in readmes:
        try:
            with open(readme_file, 'r', encoding='utf-8') as f:
                raw_content = f.read()

            content = parse_markdown(raw_content)
            # Get example name from parent directory
            example_name = readme_file.parent.name.replace("lucille-", "").replace("-example", "")
            title = f"Example: {example_name.replace('-', ' ').title()}"
            relative_path = readme_file.relative_to(LUCILLE_ROOT)

            docs, chunks = ingest_document(
                str(uuid4()),
                content,
                title,
                str(relative_path),
                "example",
                embeddings,
                client=_get_client(),
            )
            total_docs += docs
            total_chunks += chunks

        except Exception as e:
            logger.warning(f"Error processing example {readme_file}: {e}")
            continue

    print(f"      ✓ Ingested {total_docs} example guides ({total_chunks} chunks)")
    return total_docs, total_chunks


def ingest_project_readme(embeddings: GoogleGenerativeAIEmbeddings) -> Tuple[int, int]:
    """Ingest the main Lucille README."""
    print("\n   📄 Ingesting project README...")

    if not LUCILLE_README.exists():
        print(f"      ⚠ Project README not found")
        return 0, 0

    try:
        with open(LUCILLE_README, 'r', encoding='utf-8') as f:
            raw_content = f.read()

        content = parse_markdown(raw_content)
        title = "Lucille: Production-Grade Search ETL"
        relative_path = LUCILLE_README.relative_to(LUCILLE_ROOT)

        docs, chunks = ingest_document(
            str(uuid4()),
            content,
            title,
            str(relative_path),
            "overview",
            embeddings,
            client=_get_client(),
        )

        if docs > 0:
            print(f"      ✓ Ingested project overview ({chunks} chunks)")

        return docs, chunks

    except Exception as e:
        logger.warning(f"Error processing project README: {e}")
        return 0, 0


def ingest_lucille_docs(javadoc_only: bool = False) -> Tuple[int, int]:
    """
    Ingest comprehensive Lucille documentation into OpenSearch.

    Args:
        javadoc_only: If True, only ingest javadoc files (legacy mode)

    Returns:
        Tuple of (total_docs, total_chunks)
    """
    print("\n📚 Ingesting Lucille documentation...")

    # Initialize embeddings
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDINGS_MODEL,
        output_dimensionality=VECTOR_DIMENSION,
    )

    # Initialize OpenSearch client and ensure index exists
    client = create_opensearch_client()
    ensure_index_exists(client)

    # Store client on module level for use by sub-functions
    _set_client(client)

    total_docs = 0
    total_chunks = 0

    # Always ingest javadoc
    docs, chunks = ingest_javadoc_files(embeddings)
    total_docs += docs
    total_chunks += chunks

    if not javadoc_only:
        # Ingest all other documentation sources
        docs, chunks = ingest_project_readme(embeddings)
        total_docs += docs
        total_chunks += chunks

        docs, chunks = ingest_markdown_docs(embeddings)
        total_docs += docs
        total_chunks += chunks

        docs, chunks = ingest_config_examples(embeddings)
        total_docs += docs
        total_chunks += chunks

        docs, chunks = ingest_example_readmes(embeddings)
        total_docs += docs
        total_chunks += chunks

    # Refresh index to make all documents searchable
    client.indices.refresh(index=OPENSEARCH_INDEX_NAME)

    # Generate catalog documents from enriched metadata
    try:
        from catalog_generator import generate_catalog_documents
        catalog_docs, catalog_chunks = generate_catalog_documents(embeddings, client)
        total_docs += catalog_docs
        total_chunks += catalog_chunks
        print(f"\n   📋 Generated {catalog_docs} catalog documents ({catalog_chunks} chunks)")
    except ImportError:
        print("\n   ⚠ catalog_generator module not available, skipping catalog generation")
    except Exception as e:
        print(f"\n   ⚠ Catalog generation failed: {e}")

    # Final refresh
    client.indices.refresh(index=OPENSEARCH_INDEX_NAME)

    return total_docs, total_chunks


# Module-level client for sub-functions that can't accept client parameter
_module_client = None


def _set_client(client):
    global _module_client
    _module_client = client


def _get_client():
    global _module_client
    if _module_client is None:
        _module_client = create_opensearch_client()
    return _module_client


def show_stats():
    """Show current documentation stats in OpenSearch."""
    try:
        client = _get_client()

        # Count total chunks in index
        count = client.count(index=OPENSEARCH_INDEX_NAME)["count"]

        # Count by collection_id using aggregation
        agg_body = {
            "size": 0,
            "aggs": {
                "collections": {
                    "terms": {"field": "collection_id", "size": 100}
                },
                "doc_types": {
                    "terms": {"field": "doc_type", "size": 100}
                },
                "unique_docs": {
                    "cardinality": {"field": "document_id"}
                },
            },
        }
        response = client.search(index=OPENSEARCH_INDEX_NAME, body=agg_body)

        print(f"\n📊 Documentation Statistics (OpenSearch index: {OPENSEARCH_INDEX_NAME}):")
        print(f"   Total chunks: {count}")

        unique_docs = response["aggregations"]["unique_docs"]["value"]
        print(f"   Unique documents: {unique_docs}")

        print("   By collection:")
        for bucket in response["aggregations"]["collections"]["buckets"]:
            print(f"      {bucket['key']}: {bucket['doc_count']} chunks")

        print("   By doc_type:")
        for bucket in response["aggregations"]["doc_types"]["buckets"]:
            print(f"      {bucket['key']}: {bucket['doc_count']} chunks")

    except Exception as e:
        print(f"   ✗ Error fetching stats: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest comprehensive Lucille documentation into vector store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_lucille_docs.py              # Ingest all documentation
  python ingest_lucille_docs.py --stats      # Show current stats only
  python ingest_lucille_docs.py --javadoc-only  # Only javadoc (legacy mode)
        """
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show current documentation stats only"
    )
    parser.add_argument(
        "--javadoc-only",
        action="store_true",
        help="Only ingest javadoc files (legacy mode, excludes guides, examples, configs)"
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    try:
        if args.stats:
            show_stats()
        else:
            docs, chunks = ingest_lucille_docs(javadoc_only=args.javadoc_only)
            print(f"\n✅ Successfully ingested {docs} Lucille documents ({chunks} chunks)")
            show_stats()
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
