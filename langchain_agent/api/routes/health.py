"""
Health check endpoints for monitoring API and dependencies.
"""

import os
import sys
from pathlib import Path

import psycopg
from fastapi import APIRouter, Request

# Add parent directory to path for config import (dynamic, not hardcoded)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URL, GOOGLE_API_KEY, OPENSEARCH_INDEX_NAME, VECTOR_COLLECTION_NAME

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Check health of API and all dependencies.

    Returns:
        Health status of postgres, google_ai, vector_store, and overall system.
    """
    status = {
        "status": "ok",
        "postgres": False,
        "google_ai": False,
        "vector_store": False,
    }

    # Check PostgreSQL (with connection timeout) - used for checkpoints
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                status["postgres"] = True
    except Exception as e:
        status["postgres_error"] = str(e)

    # Check OpenSearch vector store has documents
    try:
        from vector_store import create_opensearch_client
        client = create_opensearch_client()
        result = client.count(
            index=OPENSEARCH_INDEX_NAME,
            body={"query": {"term": {"collection_id": VECTOR_COLLECTION_NAME}}},
        )
        doc_count = result["count"]
        status["vector_store"] = doc_count > 0
        status["document_count"] = doc_count
    except Exception as e:
        status["vector_store_error"] = str(e)

    # Check Google AI API key is configured
    status["google_ai"] = bool(GOOGLE_API_KEY)
    if not GOOGLE_API_KEY:
        status["google_ai_error"] = "GOOGLE_API_KEY not set"

    # Overall status
    if not all([status["postgres"], status["google_ai"]]):
        status["status"] = "degraded"

    return status


@router.get("/health/ready")
async def readiness_check():
    """
    Kubernetes-style readiness probe.
    Returns 200 if ready to accept traffic.
    """
    health = await health_check()
    if health["status"] == "ok":
        return {"ready": True}
    return {"ready": False, "reason": health}


@router.get("/config")
async def get_frontend_config(request: Request):
    """
    Runtime configuration for frontend.
    Allows frontend to discover the API URL at runtime instead of build time.
    """
    # Get the origin URL from the request
    origin = request.headers.get("origin", "")

    # Determine API base URL
    # In production (Cloud Run), use the origin URL
    # In development, use localhost:8000
    if origin and origin.startswith("https://"):
        api_url = origin
    else:
        api_url = os.environ.get("API_URL", "")

    return {
        "apiUrl": api_url,
    }
