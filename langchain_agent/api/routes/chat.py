"""
WebSocket endpoint for real-time chat with agent observability.
"""

import asyncio
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import RATE_LIMIT_CHAT
from api.schemas.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    ConnectionEstablished,
    BaseEvent,
)
from api.middleware.origin_auth import verify_websocket_origin, verify_same_origin
from logging_config import get_logger

logger = get_logger(__name__)

# Thread ID pattern: starts with letter, alphanumeric with underscores/hyphens, max 64 chars
THREAD_ID_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')

# Initialize limiter (will use app.state.limiter)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


# ============================================================================
# CONNECTION MANAGER
# ============================================================================


class ConnectionManager:
    """Manages WebSocket connections and message routing."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}  # Track running agent tasks
        self._agent_service = None  # Lazy initialization

    @property
    def agent_service(self):
        """Lazy load agent service to avoid slow startup."""
        if self._agent_service is None:
            from api.services.observable_agent import ObservableAgentService
            self._agent_service = ObservableAgentService()
        return self._agent_service

    async def connect(self, websocket: WebSocket, thread_id: str) -> bool:
        """
        Accept WebSocket connection and register it.

        Args:
            websocket: The WebSocket connection
            thread_id: Conversation thread ID

        Returns:
            True if connection successful
        """
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        return True

    async def disconnect(self, thread_id: str):
        """Remove connection from active connections and cancel any running task."""
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        # Cancel running task if any
        if thread_id in self.running_tasks:
            task = self.running_tasks[thread_id]
            if not task.done():
                task.cancel()
            del self.running_tasks[thread_id]

    def register_task(self, thread_id: str, task: asyncio.Task):
        """Register a running agent task for a thread."""
        self.running_tasks[thread_id] = task

    async def cancel_task(self, thread_id: str):
        """Cancel the running task for a thread."""
        if thread_id in self.running_tasks:
            task = self.running_tasks[thread_id]
            if not task.done():
                logger.info("cancelling_agent_task", thread_id=thread_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # Expected
            del self.running_tasks[thread_id]

    async def emit_event(self, thread_id: str, event: BaseEvent):
        """
        Send an event to a specific connection.

        Args:
            thread_id: Target connection's thread ID
            event: Event to send
        """
        if thread_id in self.active_connections:
            websocket = self.active_connections[thread_id]
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except Exception as e:
                logger.error("websocket_send_error", thread_id=thread_id, error=str(e))

    def get_connection_count(self) -> int:
        """Return number of active connections."""
        return len(self.active_connections)

    async def shutdown(self):
        """
        Shutdown the connection manager and clean up resources.

        This should be called during application shutdown to properly
        release memory held by the agent service, including models and
        database connections.
        """
        # Close all active connections
        for thread_id in list(self.active_connections.keys()):
            try:
                websocket = self.active_connections[thread_id]
                await websocket.close()
            except Exception as e:
                logger.error("websocket_close_error", thread_id=thread_id, error=str(e))
        self.active_connections.clear()

        # Cleanup agent service if initialized
        if self._agent_service is not None:
            try:
                await self._agent_service.cleanup()
                self._agent_service = None
            except Exception as e:
                logger.error("agent_service_cleanup_error", error=str(e))


# Global connection manager instance
manager = ConnectionManager()


# ============================================================================
# REQUEST MODELS
# ============================================================================


class ChatMessage(BaseModel):
    """Incoming chat message from client with validation."""

    type: str = "chat_message"
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User message content (1-4000 characters)"
    )
    thread_id: Optional[str] = Field(
        None,
        description="Conversation thread ID (optional)"
    )

    @field_validator('thread_id')
    @classmethod
    def validate_thread_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not THREAD_ID_PATTERN.match(v):
            raise ValueError(
                'thread_id must start with a letter and contain only '
                'alphanumeric characters, underscores, or hyphens (max 64 chars)'
            )
        return v

    @field_validator('message')
    @classmethod
    def validate_message_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('message cannot be empty or whitespace only')
        return v


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for chat with real-time observability.

    Protocol:
        1. Client connects from UI (same-origin)
        2. Server verifies origin authentication
        3. Server sends connection_established event
        4. Client sends chat_message events
        5. Server streams observability events as agent executes
        6. Server sends agent_complete or agent_error when done

    Query Parameters:
        thread_id: Conversation thread ID (optional, generated if not provided)

    Client Message Format:
        {
            "type": "chat_message",
            "message": "What is LangGraph?",
            "thread_id": "conv_abc123"  // optional
        }

    Server Event Format:
        See api/schemas/events.py for all event types
    """
    # Verify same-origin authentication before accepting connection
    if not await verify_websocket_origin(websocket):
        return  # Connection closed by verify function

    # Get or generate thread ID
    thread_id = websocket.query_params.get("thread_id")
    if not thread_id:
        thread_id = f"conversation_{uuid.uuid4().hex[:8]}"

    # Accept connection
    await manager.connect(websocket, thread_id)

    # Load existing message count from checkpoint
    existing_count = 0
    try:
        pool = manager.agent_service._agent.async_pool if manager.agent_service and manager.agent_service._agent else None

        if pool:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Query checkpoint_blobs for existing messages
                    await cur.execute("""
                        SELECT blob, type
                        FROM checkpoint_blobs
                        WHERE thread_id = %s
                          AND channel = 'messages'
                        ORDER BY version DESC
                        LIMIT 1
                    """, (thread_id,))

                    blob_row = await cur.fetchone()

                    if blob_row and blob_row[0]:
                        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
                        blob, blob_type = blob_row
                        serializer = JsonPlusSerializer()
                        raw_messages = serializer.loads_typed((blob_type, blob))

                        # Count human and AI messages with content
                        existing_count = sum(
                            1 for msg in raw_messages
                            if hasattr(msg, 'type') and msg.type in ('human', 'ai')
                            and hasattr(msg, 'content') and msg.content
                        )
    except Exception as e:
        logger.warning("message_count_load_error", thread_id=thread_id, error=str(e))

    # Send connection established event
    await manager.emit_event(
        thread_id,
        ConnectionEstablished(
            thread_id=thread_id,
            existing_messages=existing_count,
        )
    )

    try:
        # Ensure agent service is initialized
        await manager.agent_service.ensure_initialized()

        while True:
            # Wait for client message
            data = await websocket.receive_json()

            if data.get("type") == "stop_execution":
                # Handle stop request
                stop_thread_id = data.get("thread_id", thread_id)
                logger.info("stop_execution_requested", thread_id=stop_thread_id)
                await manager.cancel_task(stop_thread_id)
                continue

            if data.get("type") == "chat_message":
                message = data.get("message", "").strip()
                msg_thread_id = data.get("thread_id", thread_id)

                if not message:
                    continue

                # Create emit callback for this request
                async def emit_callback(event: BaseEvent):
                    await manager.emit_event(msg_thread_id, event)

                # Create and register the processing task
                async def process_task():
                    try:
                        await manager.agent_service.process_message(
                            message=message,
                            thread_id=msg_thread_id,
                            emit=emit_callback,
                        )
                    except asyncio.CancelledError:
                        logger.info("agent_task_cancelled", thread_id=msg_thread_id)
                        # Notify client that execution was cancelled
                        await manager.emit_event(
                            msg_thread_id,
                            AgentErrorEvent(
                                error="Execution stopped by user",
                                recoverable=True,
                            )
                        )
                    except Exception as e:
                        logger.error("agent_processing_error", thread_id=msg_thread_id, error=str(e))
                        await manager.emit_event(
                            msg_thread_id,
                            AgentErrorEvent(
                                error=str(e),
                                recoverable=True,
                            )
                        )
                    finally:
                        # Clean up the task reference
                        if msg_thread_id in manager.running_tasks:
                            del manager.running_tasks[msg_thread_id]

                # Create task and register it
                task = asyncio.create_task(process_task())
                manager.register_task(msg_thread_id, task)

    except WebSocketDisconnect:
        logger.info("websocket_disconnected", thread_id=thread_id)
    except Exception as e:
        logger.error("websocket_error", thread_id=thread_id, error=str(e))
    finally:
        # Always cleanup connection and cancel any running tasks
        logger.info("websocket_cleanup", thread_id=thread_id)
        await manager.disconnect(thread_id)


# ============================================================================
# REST FALLBACK (for testing without WebSocket)
# ============================================================================


class ChatRequest(BaseModel):
    """REST chat request (non-streaming fallback) with validation."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User message content (1-4000 characters)"
    )
    thread_id: Optional[str] = Field(
        None,
        description="Conversation thread ID (optional)"
    )

    @field_validator('thread_id')
    @classmethod
    def validate_thread_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not THREAD_ID_PATTERN.match(v):
            raise ValueError(
                'thread_id must start with a letter and contain only '
                'alphanumeric characters, underscores, or hyphens (max 64 chars)'
            )
        return v

    @field_validator('message')
    @classmethod
    def validate_message_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('message cannot be empty or whitespace only')
        return v


class Citation(BaseModel):
    """Citation source for a response."""
    label: str
    url: str


class ChatResponse(BaseModel):
    """REST chat response."""

    thread_id: str
    response: str
    duration_ms: float
    citations: List[Citation] = []


@router.post("/api/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_rest(request: Request, chat_request: ChatRequest):
    """
    REST endpoint for chat (non-streaming fallback).

    For real-time streaming with observability, use the WebSocket endpoint.

    Requires same-origin authentication.

    Args:
        request: FastAPI request object (for auth and rate limiting)
        chat_request: Chat request with message and optional thread_id

    Returns:
        Chat response with agent's answer.
    """
    # Verify same-origin authentication
    await verify_same_origin(request)

    thread_id = chat_request.thread_id or f"conversation_{uuid.uuid4().hex[:8]}"

    start_time = datetime.utcnow()

    # Collect events (we won't stream them in REST mode)
    events = []

    async def collect_event(event: BaseEvent):
        events.append(event)

    await manager.agent_service.ensure_initialized()

    try:
        final_response = await manager.agent_service.process_message(
            message=chat_request.message,
            thread_id=thread_id,
            emit=collect_event,
        )

        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Extract citations from the agent complete event
        citations: List[Citation] = []
        for event in events:
            if isinstance(event, AgentCompleteEvent) and event.citations:
                citations = [
                    Citation(label=c.get("label", ""), url=c.get("url", ""))
                    for c in event.citations
                    if c.get("url")  # Only include citations with URLs
                ]
                break

        return ChatResponse(
            thread_id=thread_id,
            response=final_response or "No response generated",
            duration_ms=duration_ms,
            citations=citations,
        )
    except Exception as e:
        raise Exception(f"Agent error: {e}")
