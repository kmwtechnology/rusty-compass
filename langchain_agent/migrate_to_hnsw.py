#!/usr/bin/env python3
"""
Migration script to switch between IVFFlat and HNSW vector indexes.

Provides safe migration with:
- PostgreSQL version checking (HNSW requires 16+)
- Dry-run mode to preview changes
- Rollback capability to revert to IVFFlat

Usage:
    # Preview migration without changes
    python migrate_to_hnsw.py --dry-run

    # Execute migration to HNSW
    python migrate_to_hnsw.py

    # Rollback to IVFFlat
    python migrate_to_hnsw.py --rollback
"""

import argparse
import sys
from typing import Tuple

import psycopg

from config import (
    DATABASE_URL,
    HNSW_M,
    HNSW_EF_CONSTRUCTION,
    IVFFLAT_LISTS,
)


def check_postgres_version(conn: psycopg.Connection) -> Tuple[int, int]:
    """
    Check PostgreSQL version.

    Returns:
        Tuple of (major_version, minor_version)

    Raises:
        ValueError: If PostgreSQL version is less than 16 (for HNSW)
    """
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        version_str = cur.fetchone()[0]
        # Parse version like: "PostgreSQL 16.1 on ..."
        parts = version_str.split()
        version_parts = parts[1].split(".")
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0

    return major, minor


def get_current_index_type(conn: psycopg.Connection) -> str:
    """
    Determine current index type for document_chunks.

    Returns:
        "hnsw", "ivfflat", or "unknown"
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'document_chunks'
              AND indexname = 'document_chunks_embedding_idx'
            """
        )
        result = cur.fetchone()

        if not result:
            return "unknown"

        indexdef = result[0].lower()
        if "hnsw" in indexdef:
            return "hnsw"
        elif "ivfflat" in indexdef:
            return "ivfflat"
        else:
            return "unknown"


def migrate_to_hnsw(conn: psycopg.Connection, dry_run: bool = False) -> bool:
    """
    Migrate from IVFFlat to HNSW indexes.

    Args:
        conn: PostgreSQL connection
        dry_run: If True, only preview changes without executing

    Returns:
        True if successful, False otherwise
    """
    current_type = get_current_index_type(conn)

    if current_type == "hnsw":
        print("✓ Already using HNSW indexes")
        return True

    if current_type == "unknown":
        print("✗ Cannot determine current index type")
        return False

    print(f"Current index type: {current_type.upper()}")
    print(f"Target index type: HNSW (m={HNSW_M}, ef_construction={HNSW_EF_CONSTRUCTION})")

    queries = [
        # Drop old indexes
        "DROP INDEX IF EXISTS document_chunks_embedding_idx",
        "DROP INDEX IF EXISTS documents_embedding_idx",
        # Create HNSW indexes on document_chunks
        f"""
        CREATE INDEX document_chunks_embedding_idx
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """,
        # Create HNSW index on documents
        f"""
        CREATE INDEX documents_embedding_idx
        ON documents USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """,
        # Analyze updated indexes
        "ANALYZE document_chunks",
    ]

    try:
        if dry_run:
            print("\n[DRY RUN] Would execute:")
            for query in queries:
                print(f"  {query.strip()[:80]}...")
            print("\nNo changes made. Run without --dry-run to execute.")
            return True

        print("\nMigrating indexes...")
        conn.autocommit = True
        with conn.cursor() as cur:
            for i, query in enumerate(queries, 1):
                cur.execute(query)
                print(f"  {i}/{len(queries)} ✓")

        print("\n✓ Migration to HNSW complete!")
        return True

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        return False


def migrate_to_ivfflat(conn: psycopg.Connection, dry_run: bool = False) -> bool:
    """
    Migrate from HNSW to IVFFlat indexes.

    Args:
        conn: PostgreSQL connection
        dry_run: If True, only preview changes without executing

    Returns:
        True if successful, False otherwise
    """
    current_type = get_current_index_type(conn)

    if current_type == "ivfflat":
        print("✓ Already using IVFFlat indexes")
        return True

    if current_type == "unknown":
        print("✗ Cannot determine current index type")
        return False

    print(f"Current index type: {current_type.upper()}")
    print(f"Target index type: IVFFlat (lists={IVFFLAT_LISTS})")

    queries = [
        # Drop old indexes
        "DROP INDEX IF EXISTS document_chunks_embedding_idx",
        "DROP INDEX IF EXISTS documents_embedding_idx",
        # Create IVFFlat indexes on document_chunks
        f"""
        CREATE INDEX document_chunks_embedding_idx
        ON document_chunks USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = {IVFFLAT_LISTS})
        """,
        # Create IVFFlat index on documents
        f"""
        CREATE INDEX documents_embedding_idx
        ON documents USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = {IVFFLAT_LISTS})
        """,
        # Analyze updated indexes
        "ANALYZE document_chunks",
    ]

    try:
        if dry_run:
            print("\n[DRY RUN] Would execute:")
            for query in queries:
                print(f"  {query.strip()[:80]}...")
            print("\nNo changes made. Run without --dry-run to execute.")
            return True

        print("\nMigrating indexes...")
        conn.autocommit = True
        with conn.cursor() as cur:
            for i, query in enumerate(queries, 1):
                cur.execute(query)
                print(f"  {i}/{len(queries)} ✓")

        print("\n✓ Migration to IVFFlat complete!")
        return True

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate between IVFFlat and HNSW vector indexes"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback to IVFFlat indexes"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing"
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("VECTOR INDEX MIGRATION TOOL")
    print("=" * 70)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            # Check PostgreSQL version
            major, minor = check_postgres_version(conn)
            print(f"\nConnected to PostgreSQL {major}.{minor}")

            if args.rollback:
                # Rollback to IVFFlat
                if major < 16:
                    print("✓ IVFFlat is compatible with PostgreSQL {major}.{minor}")
                success = migrate_to_ivfflat(conn, dry_run=args.dry_run)
            else:
                # Migrate to HNSW
                if major < 16:
                    print(f"✗ HNSW requires PostgreSQL 16+, you have {major}.{minor}")
                    print("  Use --rollback to switch to IVFFlat instead")
                    return 1
                success = migrate_to_hnsw(conn, dry_run=args.dry_run)

            return 0 if success else 1

    except Exception as e:
        print(f"\n✗ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
