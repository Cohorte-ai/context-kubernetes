"""Context Kubernetes — FastAPI Application.

The Context API: 15 operations over HTTPS + WebSocket + JWT auth.
This is the single entry point for all agent communication —
analogous to the Kubernetes API server.

Endpoints map directly to the AIOS Protocol from the paper:
  SESSION:   POST /sessions, DELETE /sessions/{id}
  CONTEXT:   POST /context/request
  ACTIONS:   POST /actions/submit, GET /actions/{id}
  APPROVALS: POST /approvals/{id}/resolve
  AUDIT:     GET /audit/events
  HEALTH:    GET /health, GET /health/sources
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from context_kubernetes.models import (
    ActionRequest,
    ApprovalTier,
    ContextRequest,
    ContextResponse,
    AuditEvent,
)
from context_kubernetes.api.state import AppState, get_state


# -----------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down application state."""
    state = get_state()
    await state.initialize()
    yield
    await state.shutdown()


# -----------------------------------------------------------------------
# App
# -----------------------------------------------------------------------

app = FastAPI(
    title="Context Kubernetes",
    description="Declarative Orchestration of Enterprise Knowledge for Agentic AI Systems",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------
# Request/Response models
# -----------------------------------------------------------------------

class SessionCreate(BaseModel):
    user_id: str
    agent_id: str
    role: str
    workspace_scope: str = ""


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    role: str
    active: bool


class ActionSubmit(BaseModel):
    session_id: str
    action_type: str
    resource: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ActionResponse(BaseModel):
    action_id: str = ""
    tier: str
    status: str  # autonomous | pending_approval | denied | excluded
    approval_id: str = ""
    message: str = ""


class ApprovalResolve(BaseModel):
    approved: bool
    verification_code: str | None = None  # for T3


class ApprovalResolveResponse(BaseModel):
    approval_id: str
    resolved: bool
    approved: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    sources: dict[str, str] = Field(default_factory=dict)
    reconciliation_cycles: int = 0


class AuditQuery(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    event_type: str | None = None
    limit: int = 100


_start_time = time.time()


# -----------------------------------------------------------------------
# SESSION endpoints
# -----------------------------------------------------------------------

@app.post("/sessions", response_model=SessionResponse)
async def create_session(req: SessionCreate, state: AppState = Depends(get_state)):
    """Create an authenticated agent session."""
    try:
        session = state.permission_engine.create_session(
            user_id=req.user_id,
            agent_id=req.agent_id,
            role=req.role,
            workspace_scope=req.workspace_scope,
        )
        return SessionResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            role=session.role,
            active=session.active,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.delete("/sessions/{session_id}")
async def kill_session(session_id: str, state: AppState = Depends(get_state)):
    """Kill switch: terminate a session immediately."""
    state.permission_engine.kill_session(session_id)
    return {"killed": session_id}


@app.delete("/sessions")
async def kill_all_sessions(user_id: str | None = None, state: AppState = Depends(get_state)):
    """Kill switch: terminate all sessions (optionally for a specific user)."""
    count = state.permission_engine.kill_all_sessions(user_id=user_id)
    return {"killed": count, "scope": user_id or "all"}


# -----------------------------------------------------------------------
# CONTEXT endpoint (the core — Definition 3.4)
# -----------------------------------------------------------------------

@app.post("/context/request", response_model=ContextResponse)
async def request_context(req: ContextRequest, state: AppState = Depends(get_state)):
    """
    Request context by intent.

    This is the Context Endpoint (Definition 3.4):
    ε(q, ω, α) → {u₁, ..., uₖ} subject to permissions, freshness, and budget.
    """
    response = await state.router.route(req)

    # Log to audit
    state.audit_log.log(AuditEvent(
        session_id=req.session_id,
        user_id=_resolve_user(state, req.session_id),
        event_type="context_request",
        operation="route",
        resource=req.intent[:100],
        outcome=f"{len(response.units)} units, {response.total_tokens} tokens",
        latency_ms=response.latency_ms,
    ))

    return response


# -----------------------------------------------------------------------
# ACTION endpoints
# -----------------------------------------------------------------------

@app.post("/actions/submit", response_model=ActionResponse)
async def submit_action(req: ActionSubmit, state: AppState = Depends(get_state)):
    """
    Submit an action for execution.

    The Permission Engine determines the approval tier:
    T1 → execute immediately
    T2 → return pending_approval (user confirms in UI)
    T3 → return pending_approval (OTP sent out-of-band)
    Excluded → denied
    """
    tier, reason = state.permission_engine.authorize(
        req.session_id, req.action_type, req.resource
    )

    action = ActionRequest(
        session_id=req.session_id,
        action_type=req.action_type,
        resource=req.resource,
        parameters=req.parameters,
    )

    if tier == ApprovalTier.AUTONOMOUS:
        state.audit_log.log(AuditEvent(
            session_id=req.session_id,
            user_id=_resolve_user(state, req.session_id),
            event_type="action_executed",
            operation=req.action_type,
            resource=req.resource,
            outcome="autonomous",
        ))
        return ActionResponse(
            tier=tier.value,
            status="autonomous",
            message=f"Action authorized (T1): {reason}",
        )

    elif tier == ApprovalTier.EXCLUDED:
        state.audit_log.log(AuditEvent(
            session_id=req.session_id,
            user_id=_resolve_user(state, req.session_id),
            event_type="action_denied",
            operation=req.action_type,
            resource=req.resource,
            outcome="excluded",
        ))
        return ActionResponse(
            tier=tier.value,
            status="excluded",
            message=f"Action not in agent profile: {req.action_type}. Manual action required.",
        )

    else:
        # T2 or T3 — create approval request
        approval = state.permission_engine.request_approval(
            req.session_id, action, tier
        )
        return ActionResponse(
            tier=tier.value,
            status="pending_approval",
            approval_id=approval.approval_id,
            message=f"Approval required ({tier.value}): {approval.description}",
        )


@app.post("/approvals/{approval_id}/resolve", response_model=ApprovalResolveResponse)
async def resolve_approval(
    approval_id: str,
    req: ApprovalResolve,
    state: AppState = Depends(get_state),
):
    """
    Resolve a pending approval.

    For T2: just approved=true/false.
    For T3: requires verification_code from the out-of-band channel.

    Design Invariant 3.8: In production, this endpoint requires a
    SEPARATE auth token bound to the user's identity, not the agent's
    session. The agent cannot call this endpoint.
    """
    # Try T2 first
    result = state.permission_engine.resolve_approval_t2(approval_id, req.approved)
    if result or not req.approved:
        return ApprovalResolveResponse(
            approval_id=approval_id,
            resolved=True,
            approved=result,
        )

    # Try T3 (needs verification code)
    if req.verification_code:
        result = state.permission_engine.resolve_approval_t3(
            approval_id, req.verification_code
        )
        return ApprovalResolveResponse(
            approval_id=approval_id,
            resolved=True,
            approved=result,
        )

    return ApprovalResolveResponse(
        approval_id=approval_id,
        resolved=False,
        approved=False,
    )


# -----------------------------------------------------------------------
# AUDIT endpoint
# -----------------------------------------------------------------------

@app.post("/audit/events", response_model=list[AuditEvent])
async def query_audit(query: AuditQuery, state: AppState = Depends(get_state)):
    """Query the audit log with filters."""
    return state.audit_log.query(
        session_id=query.session_id,
        user_id=query.user_id,
        event_type=query.event_type,
        limit=query.limit,
    )


@app.get("/audit/count")
async def audit_count(event_type: str | None = None, state: AppState = Depends(get_state)):
    """Count audit events."""
    return {"count": state.audit_log.count(event_type)}


# -----------------------------------------------------------------------
# HEALTH endpoints
# -----------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health(state: AppState = Depends(get_state)):
    """System health check."""
    source_health = state.reconciliation.get_source_health()
    recon_state = state.reconciliation.get_state()

    return HealthResponse(
        status="healthy" if all(h.value == "healthy" for h in source_health.values()) else "degraded",
        version="0.1.0",
        uptime_seconds=time.time() - _start_time,
        sources={name: h.value for name, h in source_health.items()},
        reconciliation_cycles=recon_state.cycle_count,
    )


@app.get("/health/sources")
async def source_health(state: AppState = Depends(get_state)):
    """Detailed source health and freshness."""
    health = state.reconciliation.get_source_health()
    freshness = state.reconciliation.get_freshness()
    return {
        name: {"health": health[name].value, "freshness": freshness[name].value}
        for name in health
    }


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _resolve_user(state: AppState, session_id: str) -> str:
    """Resolve user_id from session_id."""
    session = state.permission_engine.get_session(session_id)
    return session.user_id if session else "unknown"
