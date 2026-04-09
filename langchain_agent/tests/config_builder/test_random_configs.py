#!/usr/bin/env python3
"""
20 diverse config builder stress tests across the full component catalog.
Each test runs through the complete LangGraph pipeline: resolve → generate → validate.

Usage:
    cd langchain_agent && source .venv/bin/activate
    python tests/config_builder/test_random_configs.py           # all 20
    python tests/config_builder/test_random_configs.py 1 5 12    # specific tests
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

os.environ.setdefault("ENABLE_CONFIG_VALIDATION", "true")

TEST_CASES = [
    # --- Connector variety ---
    {
        "id": 1,
        "query": "Build a pipeline that reads Parquet files, renames the columns, and indexes into Pinecone with OpenAI embeddings",
        "expected_components": ["ParquetConnector", "RenameFields", "OpenAIEmbed", "PineconeIndexer"],
    },
    {
        "id": 2,
        "query": "Create a Kafka consumer pipeline that parses incoming JSON messages, timestamps each document, and writes to OpenSearch",
        "expected_components": ["KafkaConnector", "ParseJson", "Timestamp", "OpenSearchIndexer"],
    },
    {
        "id": 3,
        "query": "I need a pipeline that reads an RSS feed, fetches each article's full HTML, extracts text with JSoup, and indexes into Elasticsearch",
        "expected_components": ["RSSConnector", "FetchUri", "ApplyJSoup", "ElasticsearchIndexer"],
    },
    {
        "id": 4,
        "query": "Build a pipeline that queries a PostgreSQL database, copies the category field to a facet field, concatenates first_name and last_name into full_name, and indexes into OpenSearch",
        "expected_components": ["DatabaseConnector", "CopyFields", "Concatenate", "OpenSearchIndexer"],
    },
    {
        "id": 5,
        "query": "Create a pipeline that reads from a Solr collection, normalizes all text fields, removes diacritics, and reindexes into a different Solr collection",
        "expected_components": ["SolrConnector", "NormalizeText", "RemoveDiacritics", "SolrIndexer"],
    },
    # --- Stage variety: text processing ---
    {
        "id": 6,
        "query": "Build a file ingestion pipeline that extracts text with Tika, chunks it by paragraph, emits each chunk as a nested child document, deletes the original binary content, and indexes into OpenSearch",
        "expected_components": ["FileConnector", "TextExtractor", "ChunkText", "EmitNestedChildren", "DeleteFields", "OpenSearchIndexer"],
    },
    {
        "id": 7,
        "query": "Create a pipeline that reads XML files, extracts data using XPath expressions, trims whitespace from all fields, and writes to a CSV file",
        "expected_components": ["FileConnector", "XPathExtractor", "TrimWhitespace", "CSVIndexer"],
    },
    {
        "id": 8,
        "query": "I need a pipeline that reads JSON files, applies a regex to extract email addresses from the body field, normalizes field names to lowercase, and indexes into Elasticsearch",
        "expected_components": ["FileConnector", "ApplyRegex", "NormalizeFieldNames", "ElasticsearchIndexer"],
    },
    # --- Stage variety: field manipulation ---
    {
        "id": 9,
        "query": "Build a database pipeline that sets a static value for the source field as 'crm_export', renames customer_id to id, drops any document where status equals deleted, and indexes into OpenSearch",
        "expected_components": ["DatabaseConnector", "SetStaticValues", "RenameFields", "DropDocument", "OpenSearchIndexer"],
    },
    {
        "id": 10,
        "query": "Create a pipeline that reads CSV files, splits the tags field by comma into individual values, removes duplicate values, removes empty fields, and writes to a new CSV file",
        "expected_components": ["FileConnector", "SplitFieldValues", "RemoveDuplicateValues", "RemoveEmptyFields", "CSVIndexer"],
    },
    # --- Stage variety: enrichment and lookup ---
    {
        "id": 11,
        "query": "Build a pipeline that reads from a database, uses a dictionary lookup to map country codes to full country names, computes the byte size of each description field, and indexes into OpenSearch",
        "expected_components": ["DatabaseConnector", "DictionaryLookup", "ComputeFieldSize", "OpenSearchIndexer"],
    },
    {
        "id": 12,
        "query": "Create a pipeline that reads files, detects the language of each document's text field, extracts the first character of the title for alphabetical bucketing, and indexes into Elasticsearch",
        "expected_components": ["FileConnector", "DetectLanguage", "ExtractFirstCharacter", "ElasticsearchIndexer"],
    },
    # --- Stage variety: dates, numbers, truncation ---
    {
        "id": 13,
        "query": "Build a Parquet ingestion pipeline that parses date strings into proper date objects, parses numeric strings to floats, truncates the description field to 1000 characters, and indexes into OpenSearch",
        "expected_components": ["ParquetConnector", "ParseDate", "ParseFloats", "TruncateField", "OpenSearchIndexer"],
    },
    {
        "id": 14,
        "query": "Create a pipeline that reads from Kafka, base64-decodes the payload field, parses the decoded content as JSON, adds a processing timestamp, and writes to Elasticsearch",
        "expected_components": ["KafkaConnector", "Base64Decode", "ParseJson", "Timestamp", "ElasticsearchIndexer"],
    },
    # --- Stage variety: filtering and conditional ---
    {
        "id": 15,
        "query": "Build a pipeline that reads CSV files, checks if the status field contains 'active' or 'pending', drops documents that don't match, copies the email field to contact_email, and indexes into OpenSearch",
        "expected_components": ["FileConnector", "Contains", "DropDocument", "CopyFields", "OpenSearchIndexer"],
    },
    {
        "id": 16,
        "query": "Create a pipeline that reads from a database, drops null values from all fields, hashes the user_id field into 10 buckets for sharding, and indexes into Elasticsearch",
        "expected_components": ["DatabaseConnector", "DropValues", "HashFieldValueToBucket", "ElasticsearchIndexer"],
    },
    # --- Complex multi-stage ---
    {
        "id": 17,
        "query": "Build a pipeline that reads files from S3, extracts text with Tika, applies a regex to find phone numbers, renames the extracted field to phone, sets a static source tag, and indexes into OpenSearch",
        "expected_components": ["FileConnector", "TextExtractor", "ApplyRegex", "RenameFields", "SetStaticValues", "OpenSearchIndexer"],
    },
    {
        "id": 18,
        "query": "Create a pipeline that reads RSS feeds, fetches each URI, parses the HTML file path, creates a static teaser from the body, and writes to a CSV file for review",
        "expected_components": ["RSSConnector", "FetchUri", "ParseFilePath", "CreateStaticTeaser", "CSVIndexer"],
    },
    # --- Unusual combinations ---
    {
        "id": 19,
        "query": "Build a pipeline that reads Parquet data, replaces patterns in the address field to standardize street abbreviations, computes field sizes for all text fields, collapses nested child documents back into parents, and indexes into Weaviate",
        "expected_components": ["ParquetConnector", "ReplacePatterns", "ComputeFieldSize", "CollapseChildrenDocuments", "WeaviateIndexer"],
    },
    {
        "id": 20,
        "query": "Create a pipeline that reads from a Solr collection, uses a dictionary to enrich product categories, splits multi-value tags by semicolon, adds a timestamp, truncates long descriptions to 500 chars, and indexes into OpenSearch",
        "expected_components": ["SolrConnector", "DictionaryLookup", "SplitFieldValues", "Timestamp", "TruncateField", "OpenSearchIndexer"],
    },
]


async def run_tests(test_ids=None):
    from main import LucilleAgent

    print("Initializing agent...")
    agent = LucilleAgent()
    agent.initialize_components()
    agent.create_agent_graph()
    print()

    cases = TEST_CASES if test_ids is None else [tc for tc in TEST_CASES if tc["id"] in test_ids]
    results = []

    for tc in cases:
        tid = f"stress-{tc['id']}"
        query = tc["query"]
        expected = tc["expected_components"]

        print(f"{'='*70}")
        print(f"Test {tc['id']}: {query[:75]}...")
        print(f"  Expected: {', '.join(expected)}")

        start = time.time()
        try:
            result = await agent.app.ainvoke(
                {"messages": [("human", query)]},
                config={"configurable": {"thread_id": tid}},
            )
            elapsed = time.time() - start

            intent = result.get("intent", "?")
            mode = result.get("agent_mode", "?")
            passed = result.get("config_validation_passed")
            attempts = result.get("config_validation_attempts", 0)
            components = result.get("config_components", [])
            errors = result.get("config_validation_errors", {})
            notes = result.get("config_validation_notes", [])

            comp_names = [c["name"] for c in components]
            sources = [c.get("resolution_source", "?") for c in components]
            catalog_count = sources.count("catalog")

            resolved_lower = {c["name"].lower() for c in components}
            expected_hits = sum(1 for e in expected if e.lower() in resolved_lower)

            status = "PASS" if passed else "FAIL"
            if intent != "config_request":
                status = "WRONG_INTENT"

            print(f"  Intent: {intent} | Mode: {mode} | Time: {elapsed:.1f}s")
            print(f"  Resolved ({len(components)}): {', '.join(comp_names)}")
            print(f"  Sources: {catalog_count}/{len(components)} from catalog")
            print(f"  Expected match: {expected_hits}/{len(expected)}")
            print(f"  Validation: {'PASSED' if passed else 'FAILED'} (attempt {attempts})")

            if errors:
                for comp, errs in list(errors.items())[:3]:
                    for e in errs[:2]:
                        print(f"  Error: {comp}: {e[:80]}")

            for n in notes:
                print(f"  Note: {n[:80]}")

            results.append({
                "id": tc["id"],
                "status": status,
                "intent": intent,
                "validation_passed": passed,
                "validation_attempts": attempts,
                "components_resolved": len(components),
                "catalog_resolved": catalog_count,
                "expected_hit_rate": f"{expected_hits}/{len(expected)}",
                "elapsed": round(elapsed, 1),
            })

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append({
                "id": tc["id"],
                "status": "ERROR",
                "error": str(e)[:100],
                "elapsed": round(elapsed, 1),
            })

        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Test':>4}  {'Status':<13} {'Valid':>5} {'Att':>3} {'Catalog':>8} {'Expected':>8} {'Time':>6}")
    print("-" * 70)

    pass_count = 0
    for r in results:
        s = r["status"]
        if s == "PASS":
            pass_count += 1
        v = str(r.get("validation_passed", "?"))
        a = str(r.get("validation_attempts", "?"))
        c = f"{r.get('catalog_resolved', '?')}/{r.get('components_resolved', '?')}"
        e = r.get("expected_hit_rate", "?")
        t = f"{r['elapsed']}s"
        print(f"  {r['id']:>2}   {s:<13} {v:>5} {a:>3} {c:>8} {e:>8} {t:>6}")

    print("-" * 70)
    print(f"  {pass_count}/{len(results)} passed")
    total = sum(r["elapsed"] for r in results)
    avg = total / len(results) if results else 0
    print(f"  Total: {total:.0f}s | Avg: {avg:.1f}s per query")

    catalog_pct = sum(r.get("catalog_resolved", 0) for r in results)
    total_comps = sum(r.get("components_resolved", 0) for r in results)
    print(f"  Catalog resolution: {catalog_pct}/{total_comps} ({100*catalog_pct//max(total_comps,1)}%)")

    attempt_1 = sum(1 for r in results if r.get("validation_attempts") == 1 and r.get("validation_passed"))
    print(f"  First-attempt validation: {attempt_1}/{len(results)}")

    return results


if __name__ == "__main__":
    # Allow running specific tests: python test_random_configs.py 1 5 12
    ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else None
    results = asyncio.run(run_tests(ids))
    failed = [r for r in results if r["status"] != "PASS"]
    sys.exit(1 if failed else 0)
