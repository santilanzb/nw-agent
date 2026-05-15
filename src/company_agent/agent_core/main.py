from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .brain.turn_log import TurnLogWriter
from .config import AgentCoreSettings
from .fsm import TurnFSM
from .llm.anthropic import LLMClient
from .routing.classifier_client import ClassifierClient
from .routing.handoff_client import HandoffClient
from .tasks.base import TaskRegistry
from .tasks.customer_service import CustomerServiceTask
from .transport.hmac_verify import verify_waha_hmac
from .transport.waha import WahaClient, normalize_waha_event

settings = AgentCoreSettings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)

# ── Singletons ────────────────────────────────────────────────────────────────

waha = WahaClient(base_url=settings.waha_base_url, api_key=settings.waha_api_key)

classifier = ClassifierClient(
    base_url=settings.rag_api_url, api_key=settings.internal_api_key
)

handoff_client = HandoffClient(
    base_url=settings.crm_adapter_url, api_key=settings.internal_api_key
)

llm = LLMClient(
    api_key=settings.anthropic_api_key,
    default_model=settings.anthropic_default_model,
    escalation_model=settings.anthropic_escalation_model,
    langfuse_public_key=settings.langfuse_public_key,
    langfuse_secret_key=settings.langfuse_secret_key,
    langfuse_host=settings.langfuse_host,
)

registry = TaskRegistry()
registry.register(CustomerServiceTask(llm=llm))

turn_log = TurnLogWriter(database_url=settings.database_url)

fsm = TurnFSM(
    waha=waha,
    classifier=classifier,
    handoff_client=handoff_client,
    registry=registry,
    turn_log=turn_log,
    team_group_jid=settings.handoff_team_group_jid,
    database_url=settings.database_url,
)

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="NutriWhite Brain — agent-core", version="0.1.0")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "agent-core"})


@app.post("/webhooks/waha")
async def waha_webhook(request: Request) -> Response:
    body = await request.body()

    # HMAC verification — reject without valid signature
    if settings.waha_hook_hmac_key:
        sig = request.headers.get("X-Webhook-Hmac", "")
        if not sig:
            logger.warning("waha webhook missing X-Webhook-Hmac header")
            raise HTTPException(status_code=401, detail="Missing HMAC signature")
        if not verify_waha_hmac(body, sig, settings.waha_hook_hmac_key):
            logger.warning("waha webhook HMAC mismatch")
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    try:
        raw_data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg = normalize_waha_event(raw_data)
    if msg is None:
        # Not a message event we care about; acknowledge and skip
        return Response(status_code=204)

    asyncio.create_task(fsm.handle(msg))

    return Response(status_code=200)


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.post("/admin/handoff/resume")
async def admin_resume(request: Request) -> JSONResponse:
    """Admin shortcut: resume handoff for a phone. Used during smoke tests."""
    data = await request.json()
    phone = data.get("contact_phone", "")
    if not phone:
        raise HTTPException(status_code=400, detail="contact_phone required")
    result = await handoff_client.resume(phone)
    return JSONResponse(result)


@app.get("/admin/tasks")
async def admin_tasks() -> JSONResponse:
    tasks = [{"name": t.name, "intents": sorted(t.handled_intents)} for t in registry._tasks]
    return JSONResponse({"tasks": tasks})
