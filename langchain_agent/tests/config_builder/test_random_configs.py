#!/usr/bin/env python3
"""
Generate 10 random config builder test cases from the component catalog
and run them through the full LangGraph pipeline (resolve → generate → validate).

Usage:
    cd langchain_agent && source .venv/bin/activate
    python tests/config_builder/test_random_configs.py
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

# 10 hand-crafted test cases using diverse catalog components
TEST_CASES = [
    {
        "id": 1,
        "query": "Build a pipeline that reads Parquet files and indexes into Pinecone with vector embeddings",
        "expected_components": ["ParquetConnector", "PineconeIndexer"],
    },
    {
        "id": 2,
        "query": "Create a pipeline that ingests from a database, applies regex patterns to clean text, renames fields, and indexes into Elasticsearch",
        "expected_components": ["DatabaseConnector", "ApplyRegex", "RenameFields", "ElasticsearchIndexer"],
    },
    {
        "id": 3,
        "query": "I need a Kafka consumer pipeline that parses JSON, detects language, and writes to OpenSearch",
        "expected_components": ["KafkaConnector", "ParseJson", "DetectLanguage", "OpenSearchIndexer"],
    },
    {
        "id": 4,
        "query": "Build a pipeline that reads RSS feeds, fetches the full article content from URIs, extracts text with JSoup, and indexes into Solr",
        "expected_components": ["RSSConnector", "FetchUri", "ApplyJSoup", "SolrIndexer"],
    },
    {
        "id": 5,
        "query": "Create a CSV export pipeline that reads files, copies fields, concatenates first and last name into full_name, and writes to a CSV file",
        "expected_components": ["FileConnector", "CopyFields", "Concatenate", "CSVIndexer"],
    },
    {
        "id": 6,
        "query": "Build a pipeline that reads from a Solr collection, normalizes text, removes diacritics, trims whitespace, and reindexes into OpenSearch",
        "expected_components": ["SolrConnector", "NormalizeText", "RemoveDiacritics", "TrimWhitespace", "OpenSearchIndexer"],
    },
    {
        "id": 7,
        "query": "I need a pipeline that reads JSON files, splits field values by comma, drops empty documents, removes duplicate values, and indexes into Weaviate",
        "expected_components": ["FileConnector", "SplitFieldValues", "DropDocument", "RemoveDuplicateValues", "WeaviateIndexer"],
    },
    {
        "id": 8,
        "query": "Create a file processing pipeline that chunks text by paragraph, emits nested children documents, deletes the original content field, and indexes into OpenSearch",
        "expected_components": ["FileConnector", "ChunkText", "EmitNestedChildren", "DeleteFields", "OpenSearchIndexer"],
    },
    {
        "id": 9,
        "query": "Build a database pipeline that queries records, uses a dictionary lookup to enrich categories, sets static values for a source tag, and indexes into Elasticsearch",
        "expected_components": ["DatabaseConnector", "DictionaryLookup", "SetStaticValues", "ElasticsearchIndexer"],
    },
    {
        "id": 10,
        "query": "Create a pipeline that reads Parquet files, parses dates, computes field sizes, truncates long fields to 500 chars, and writes to a CSV file",
        "expected_components": ["ParquetConnector", "ParseDate", "ComputeFieldSize", "TruncateField", "CSVIndexer"],
    },
]


async def run_tests():
    from main import LucilleAgent

    print("Initializing agent...")
    agent = LucilleAgent()
    agent.initialize_components()
    agent.create_agent_graph()
    print()

    results = []

    for tc in TEST_CASES:
        tid = f"random-test-{tc['id']}"
        query = tc["query"]
        expected = tc["expected_components"]

        print(f"{'='*70}")
        print(f"Test {tc['id']}: {query[:80]}...")
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

            # Check how many expected components were resolved
            resolved_names_lower = {c["name"].lower() for c in components}
            expected_hits = sum(1 for e in expected if e.lower() in resolved_names_lower)

            status = "PASS" if passed else "FAIL"
            if intent != "config_request":
                status = "WRONG_INTENT"

            print(f"  Intent: {intent} | Mode: {mode} | Time: {elapsed:.1f}s")
            print(f"  Components ({len(components)}): {', '.join(comp_names)}")
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

    # Summary table
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Test':>4}  {'Status':<13} {'Valid':>5} {'Attempts':>8} {'Catalog':>8} {'Expected':>8} {'Time':>6}")
    print("-" * 70)

    pass_count = 0
    for r in results:
        s = r["status"]
        if s == "PASS":
            pass_count += 1
        v = str(r.get("validation_passed", "?"))
        a = str(r.get("validation_attempts", "?"))
        c = str(r.get("catalog_resolved", "?")) + "/" + str(r.get("components_resolved", "?"))
        e = r.get("expected_hit_rate", "?")
        t = f"{r['elapsed']}s"
        print(f"  {r['id']:>2}   {s:<13} {v:>5} {a:>8} {c:>8} {e:>8} {t:>6}")

    print("-" * 70)
    print(f"  {pass_count}/{len(results)} passed")
    total_time = sum(r["elapsed"] for r in results)
    print(f"  Total time: {total_time:.0f}s")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_tests())
    failed = [r for r in results if r["status"] != "PASS"]
    sys.exit(1 if failed else 0)
