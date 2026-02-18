"""
FastAPI application with WebSocket support for real-time agent streaming.

This is the main entry point for the LangChain Agent API.
Run with: uvicorn api.main:app --reload --port 8000
"""

import warnings

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import RATE_LIMIT_ENABLED, API_KEY
from api.routes import health, conversations, chat
from api.middleware.auth import AuthConfigurationError
from logging_config import configure_logging, get_logger

# Configure structured logging
configure_logging()
logger = get_logger(__name__)

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    enabled=RATE_LIMIT_ENABLED,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown")
    decorators with a modern async context manager pattern.
    """
    # Startup
    if not API_KEY:
        raise AuthConfigurationError(
            "API_KEY environment variable is not set. "
            "Authentication is required. Set API_KEY in your .env file."
        )

    logger.info(
        "api_started",
        rest_api="http://localhost:8000/api",
        websocket="ws://localhost:8000/ws/chat",
        docs="http://localhost:8000/docs",
        auth_required=True,
    )

    yield  # Application runs here

    # Shutdown
    logger.info("api_shutting_down")
    try:
        await chat.manager.shutdown()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    logger.info("api_shutdown_complete")


app = FastAPI(
    title="Lucille Documentation RAG API",
    description="WebSocket-based API for observing agent execution with full observability",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter

# Register rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
# Accept localhost for development plus this service's Cloud Run URL
cors_origins = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",  # Alternative dev port
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

# Add explicitly configured origins (e.g., custom domains)
if os.environ.get("CORS_ORIGINS"):
    configured_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    cors_origins.extend(configured_origins)

# Determine this service's URL for Cloud Run
# The frontend will request from the same origin, so we need to allow it
# This is set dynamically via the /api/config endpoint at runtime
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https://.*\.a\.run\.app",  # Accept all Cloud Run URLs
)

# Register REST routes
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])

# Register WebSocket route
app.include_router(chat.router, tags=["chat"])

# Mount static files for React frontend (if built)
static_dir = Path(__file__).parent.parent / "web" / "dist"
if static_dir.exists():
    # Mount assets directory
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    # Serve React app for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Serve React frontend for all non-API routes"""
        # Skip API routes
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            return JSONResponse({"error": "Not Found"}, status_code=404)

        # Serve index.html for all other routes (React Router will handle)
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        return JSONResponse({"error": "Frontend not built"}, status_code=404)
