"""
Main FastAPI Application for magicpin Vera AI Assistant.
Exposes the 5 HTTP endpoints defined in the challenge contract:
1. GET  /v1/healthz
2. GET  /v1/metadata
3. POST /v1/context
4. POST /v1/tick
5. POST /v1/reply
"""

import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import BOT_START_TIME, METADATA
from app.models.api import (
    HealthzResponse,
    MetadataResponse,
    TickRequest,
    TickResponse,
    ReplyRequest,
    ReplyResponse
)
from app.store.context_store import context_store
from app.services.context_service import context_service
from app.engine.tick_engine import tick_engine
from app.engine.reply_engine import reply_engine

app = FastAPI(
    title="magicpin Vera AI Assistant",
    description="Deterministic, stateful merchant AI assistant submission for the magicpin Vera Challenge",
    version="1.0.0"
)


@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz():
    """Liveness probe reporting uptime and loaded contexts count."""
    uptime = int(time.time() - BOT_START_TIME)
    counts = context_store.get_counts()
    return HealthzResponse(
        status="ok",
        uptime_seconds=uptime,
        contexts_loaded=counts
    )


@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata():
    """Bot identity and architecture metadata."""
    return MetadataResponse(**METADATA)


@app.post("/v1/context")
async def push_context(request: Request):
    """
    Ingest a context push (category, merchant, customer, or trigger).
    Enforces atomic versioning and returns:
    - 200 OK: Context accepted and stored
    - 409 Conflict: Stale version (version <= stored version)
    - 400 Bad Request: Invalid scope or malformed body
    """
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_json", "details": str(e)}
        )

    code, resp_content = context_service.ingest_context(body)
    return JSONResponse(status_code=code, content=resp_content)


@app.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest):
    """
    Periodic wake-up endpoint — Phase 6.
    Runs the full deterministic decision pipeline:
    resolve → validate → extract → score → compose → guardrail → record.
    Returns the list of proactive actions Vera should dispatch.
    """
    actions = tick_engine.process(
        now_iso=body.now,
        available_triggers=body.available_triggers,
    )
    return TickResponse(actions=actions)


@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest):
    """
    Multi-turn conversation reply endpoint — Phase 7.
    Runs the full deterministic conversation state machine:
    detect intent → transition state → compose grounded response → record.
    Supported actions: send | wait | end
    """
    return reply_engine.process(body)
