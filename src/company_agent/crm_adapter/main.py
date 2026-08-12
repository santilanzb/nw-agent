from __future__ import annotations

from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from company_agent.common.auth import require_internal_api_key
from company_agent.common.handoff_state import HandoffStateRecord, HandoffStateStore
from company_agent.common.logging import configure_logging

from .adapters import BaseCrmAdapter, MockCrmAdapter, ZohoCrmAdapter
from .config import CrmSettings
from .models import (
    ConsultaRecord,
    CustomerLookupRequest,
    CustomerOrdersRequest,
    CustomerProfile,
    CustomerTicketsRequest,
    DealRecord,
    ExamenRecord,
    HandoffClaimRequest,
    HandoffClaimResponse,
    HandoffRequest,
    HandoffResponse,
    HandoffResumeRequest,
    HandoffResumeResponse,
    HandoffStateCheckRequest,
    HandoffStateRecordModel,
    HealthResponse,
    TicketDraftRequest,
    TicketDraftResponse,
)

settings = CrmSettings()
logger = configure_logging(settings.app_name)


def _build_adapter() -> BaseCrmAdapter:
    if settings.crm_provider == "zoho":
        from .zoho_client import ZohoClient, ZohoTokenManager

        if not all([settings.zoho_client_id, settings.zoho_client_secret, settings.zoho_refresh_token]):
            raise RuntimeError(
                "CRM_PROVIDER=zoho requires ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN"
            )

        tokens = ZohoTokenManager(
            accounts_url=settings.zoho_accounts_url,
            client_id=settings.zoho_client_id,       # type: ignore[arg-type]
            client_secret=settings.zoho_client_secret,  # type: ignore[arg-type]
            refresh_token=settings.zoho_refresh_token,  # type: ignore[arg-type]
        )
        client = ZohoClient(api_base=settings.zoho_api_base, tokens=tokens)
        logger.info(
            "zoho adapter initialized api_base=%s sandbox=%s",
            settings.zoho_api_base,
            settings.zoho_sandbox,
        )
        return ZohoCrmAdapter(client)

    logger.info("using mock CRM adapter")
    return MockCrmAdapter()


adapter = _build_adapter()

app = FastAPI(title="CRM Adapter", version="0.2.0")
InternalApiKey = Annotated[None, Depends(require_internal_api_key(settings.internal_api_key))]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ── Customer profile (lookup by phone / id / email) ───────────────────────────

@app.post("/v1/customer/profile", response_model=CustomerProfile)
def customer_profile(request: CustomerLookupRequest, _auth: InternalApiKey) -> CustomerProfile:
    profile = adapter.lookup_customer(
        phone=request.phone,
        customer_id=request.customer_id,
        email=request.email,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return profile


# ── Deals / Plans ─────────────────────────────────────────────────────────────

@app.post("/v1/customer/orders", response_model=list[DealRecord])
def customer_orders(request: CustomerOrdersRequest, _auth: InternalApiKey) -> list[DealRecord]:
    return list(adapter.list_orders(request.customer_id))


# ── Consultas (appointments) ──────────────────────────────────────────────────

@app.post("/v1/customer/tickets", response_model=list[ConsultaRecord])
def customer_tickets(request: CustomerTicketsRequest, _auth: InternalApiKey) -> list[ConsultaRecord]:
    return list(adapter.list_tickets(request.customer_id))


@app.post("/v1/customer/consultas", response_model=list[ConsultaRecord])
def customer_consultas(request: CustomerTicketsRequest, _auth: InternalApiKey) -> list[ConsultaRecord]:
    return list(adapter.list_tickets(request.customer_id))


# ── Examenes ──────────────────────────────────────────────────────────────────

@app.post("/v1/customer/examenes", response_model=list[ExamenRecord])
def customer_examenes(request: CustomerOrdersRequest, _auth: InternalApiKey) -> list[ExamenRecord]:
    return list(adapter.list_examenes(request.customer_id))


# ── Ticket draft / note ───────────────────────────────────────────────────────

@app.post("/v1/tickets/draft", response_model=TicketDraftResponse)
def create_ticket_draft(request: TicketDraftRequest, _auth: InternalApiKey) -> TicketDraftResponse:
    logger.info("ticket draft for contact=%s", request.customer_id)
    return adapter.create_ticket_draft(request)


# ── Handoff ───────────────────────────────────────────────────────────────────

handoff_store = HandoffStateStore(
    database_url=settings.database_url,
    expire_hours=settings.handoff_expire_hours,
)


def _record_to_model(rec: HandoffStateRecord | None) -> HandoffStateRecordModel:
    """Convert a DB record into the agent-facing model. None ⇒ active=False."""
    if not rec:
        return HandoffStateRecordModel(active=False, contact_phone="")
    return HandoffStateRecordModel(
        active=rec.status in ("pending", "claimed"),
        handoff_id=rec.id,
        contact_phone=rec.contact_phone,
        contact_id=rec.contact_id,
        patient_name=rec.patient_name,
        status=rec.status,
        reason=rec.reason,
        priority=rec.priority,
        last_message=rec.last_message,
        claimed_by_phone=rec.claimed_by_phone,
        claimed_by_name=rec.claimed_by_name,
        created_at=rec.created_at.isoformat() if rec.created_at else None,
        claimed_at=rec.claimed_at.isoformat() if rec.claimed_at else None,
        expires_at=rec.expires_at.isoformat() if rec.expires_at else None,
    )


@app.post("/v1/handoff", response_model=HandoffResponse)
def handoff_human(request: HandoffRequest, _auth: InternalApiKey) -> HandoffResponse:
    """
    Fire a new handoff. Creates a Zoho Note (audit) AND a row in handoff_state
    (the runtime gate that keeps Gutty quiet while a human is on the case).
    """
    logger.info(
        "handoff conversation=%s contact=%s phone=%s",
        request.conversation_id, request.customer_id, request.contact_phone,
    )

    # A phone-less request never reaches here: `HandoffRequest.contact_phone` is
    # required, so FastAPI rejects it with 422 before the Zoho Note is written.
    # It used to fall through to a branch that logged a warning, skipped the
    # state row and returned 200 — a handoff that left an audit Note in the CRM
    # and never muted Gutty, which is the failure that looks like the agent
    # talking over an asesora.

    # 1) Zoho Note via the existing adapter path (system of record / audit)
    zoho_response = adapter.handoff(request)

    # 2) Postgres state row — the runtime gate that keeps Gutty quiet.
    state = handoff_store.create(
        contact_phone=request.contact_phone,
        reason=request.reason,
        priority=request.priority,
        contact_id=request.customer_id,
        patient_name=request.patient_name,
        conversation_id=request.conversation_id,
        last_message=request.last_message,
        zoho_note_id=zoho_response.note_id,
    )

    return HandoffResponse(
        handoff_id=state.id,
        contact_id=state.contact_id,
        note_id=state.zoho_note_id,
        status=state.status,
        message=zoho_response.message,
        expires_at=state.expires_at.isoformat(),
    )


@app.post("/v1/handoff/state/check", response_model=HandoffStateRecordModel)
def handoff_state_check(request: HandoffStateCheckRequest, _auth: InternalApiKey) -> HandoffStateRecordModel:
    """Hot path: every patient message hits this so the agent knows to stay silent."""
    rec = handoff_store.check_active(request.contact_phone)
    return _record_to_model(rec) if rec else HandoffStateRecordModel(active=False, contact_phone=request.contact_phone)


@app.post("/v1/handoff/claim", response_model=HandoffClaimResponse)
def handoff_claim(request: HandoffClaimRequest, _auth: InternalApiKey) -> HandoffClaimResponse:
    """First-to-claim. Returns success=False if someone already claimed it."""
    logger.info(
        "handoff claim contact=%s by=%s (%s)",
        request.contact_phone, request.claimer_name, request.claimer_phone,
    )

    claimed = handoff_store.claim(
        contact_phone=request.contact_phone,
        claimer_phone=request.claimer_phone,
        claimer_name=request.claimer_name,
    )
    if claimed:
        return HandoffClaimResponse(
            success=True, reason="claimed", state=_record_to_model(claimed),
        )

    # Race lost (or nothing pending). Distinguish the two so the caller can
    # reply with a precise message.
    already = handoff_store.already_claimed(request.contact_phone)
    if already:
        return HandoffClaimResponse(
            success=False, reason="already_claimed", state=_record_to_model(already),
        )
    return HandoffClaimResponse(
        success=False, reason="not_found",
        state=HandoffStateRecordModel(active=False, contact_phone=request.contact_phone),
    )


@app.post("/v1/handoff/resume", response_model=HandoffResumeResponse)
def handoff_resume(request: HandoffResumeRequest, _auth: InternalApiKey) -> HandoffResumeResponse:
    """Close the active handoff for this patient so Gutty answers again."""
    logger.info("handoff resume contact=%s", request.contact_phone)
    resumed = handoff_store.resume(request.contact_phone)
    if resumed:
        return HandoffResumeResponse(
            success=True, reason="resumed", state=_record_to_model(resumed),
        )
    return HandoffResumeResponse(
        success=False, reason="not_found",
        state=HandoffStateRecordModel(active=False, contact_phone=request.contact_phone),
    )


def run() -> None:
    uvicorn.run("company_agent.crm_adapter.main:app", host="0.0.0.0", port=8082, reload=False)


if __name__ == "__main__":
    run()
