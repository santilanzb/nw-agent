from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from company_agent.common.db import make_async_pool
from company_agent.packages.drift import PackageDrift, check_drift
from company_agent.packages.registrar import install_packages

from .brain.episodes import EpisodeStore
from .brain.turn_log import TurnLogWriter
from .config import AgentCoreSettings
from .fsm import TurnFSM, turn_id_for
from .identity import IdentityBroker
from .ingress.inbox import InboxWriter
from .llm.anthropic import LLMClient
from .media import MediaStore
from .outbox.sender import SendOutbox
from .routing.classifier_client import ClassifierClient
from .routing.handoff_client import HandoffClient
from .routing.retrieval_client import RetrievalClient
from .tasks.base import TaskRegistry
from .tasks.fallback import FallbackTask
from .transport.base import InboundEvent, Transport
from .transport.waha import WahaTransport

# psycopg's async driver refuses to run on Windows' default ProactorEventLoop and
# AsyncConnectionPool then retries forever, so the symptom is a hang rather than
# an error. No-op on Linux, where the services actually run.
if sys.platform == "win32":  # pragma: no cover - platform guard
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = AgentCoreSettings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)s}',
)
logger = logging.getLogger(__name__)

# Fail-closed startup gate. With no signing key the webhook used to skip
# verification entirely, and the setting defaults to empty — so a missing env var
# silently opened the ingress to anyone who could reach the port.
if not settings.waha_hook_hmac_key and not settings.allow_unverified_webhooks:
    raise RuntimeError(
        "WAHA_HOOK_HMAC_KEY is unset, so inbound webhooks would be accepted without "
        "signature verification. Set it, or set ALLOW_UNVERIFIED_WEBHOOKS=true for "
        "local development only."
    )

# -- Singletons ---------------------------------------------------------------

pool = make_async_pool(
    settings.database_url,
    min_size=settings.db_pool_min_size,
    max_size=settings.db_pool_max_size,
)

waha = WahaTransport(
    base_url=settings.waha_base_url,
    api_key=settings.waha_api_key,
    hmac_key=settings.waha_hook_hmac_key,
    allow_unverified=settings.allow_unverified_webhooks,
)
transports: dict[str, Transport] = {waha.name: waha}

inbox = InboxWriter(pool)
outbox = SendOutbox(pool, transports)

classifier = ClassifierClient(
    base_url=settings.rag_api_url, api_key=settings.internal_api_key
)
retrieval = RetrievalClient(
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

turn_log = TurnLogWriter(database_url=settings.database_url)
identity = IdentityBroker(pool)
episodes = EpisodeStore(pool)
media = MediaStore(pool, settings.media_root, api_key=settings.waha_api_key)

# Tasks arrive as function packages: one directory each, discovered and
# registered here. Adding a capability means adding a directory — this line
# never changes again. Packages receive the dependencies they declare in their
# constructor; a package that wants none of these simply does not accept them.
registry = TaskRegistry()
installed_packages = install_packages(
    registry, llm=llm, retrieval=retrieval, episodes=episodes
)
registry.set_fallback(FallbackTask())

fsm = TurnFSM(
    transport=waha,
    outbox=outbox,
    classifier=classifier,
    handoff_client=handoff_client,
    registry=registry,
    turn_log=turn_log,
    team_group_jid=settings.handoff_team_group_jid,
    identity=identity,
    episodes=episodes,
    media=media,
)

_inflight: set[asyncio.Task[None]] = set()


# -- Processing ---------------------------------------------------------------

async def _process(event_row_id: uuid.UUID, event: InboundEvent) -> None:
    """Run one turn and record its fate on the inbox row."""
    await inbox.mark_processing(event_row_id)
    try:
        await fsm.handle(event)
    except Exception as exc:
        logger.exception("turn failed event=%s", event.source_event_id)
        await inbox.mark_failed(event_row_id, str(exc))
        return
    await inbox.mark_processed(event_row_id, turn_id_for(event))


def _spawn(event_row_id: uuid.UUID, event: InboundEvent) -> None:
    task = asyncio.create_task(_process(event_row_id, event))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _sweeper() -> None:
    """
    Re-drive events nobody finished and resolve sends left in doubt.

    This is the durability backstop: the webhook path can die at any point after
    the ACK and the work is still owed. Interim implementation as an asyncio
    loop — the C1 fallback design — replaced by a DBOS scheduled tick once the
    Stage-0 spike passes.
    """
    while True:
        await asyncio.sleep(settings.sweeper_interval_seconds)
        try:
            rows = await inbox.claim_stale(
                pending_grace_seconds=settings.sweeper_pending_grace_seconds
            )
            for row in rows:
                wire = transports.get(row.source)
                if wire is None:
                    await inbox.mark_skipped(row.id, f"no transport for source {row.source!r}")
                    continue
                event = wire.normalize(row.payload)
                if event is None:
                    await inbox.mark_skipped(row.id, "payload no longer normalizes to an event")
                    continue
                logger.warning(
                    "re-driving unfinished event id=%s attempts=%s", row.id, row.attempts
                )
                await _process(row.id, event)

            recovered = await outbox.recover_in_doubt()
            if recovered:
                logger.warning("resolved %d in-doubt send intents", recovered)
        except Exception:
            logger.exception("sweeper tick failed")


# -- FastAPI app --------------------------------------------------------------

async def _seeded_intent_classes() -> set[str] | None:
    """What the classifier can actually match. None if the query fails."""
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute("SELECT DISTINCT intent_class FROM intent_vectors")).fetchall()
        return {row["intent_class"] for row in rows}
    except Exception:
        logger.exception("could not read seeded intent classes — skipping the database half")
        return None


async def _check_package_drift() -> None:
    """
    Three sets that must agree: declared, claimed, seeded.

    Nothing compared them before, so a seeded intent no task claimed was
    discovered one patient at a time — each one escalated to a human by the
    fallback handler.
    """
    report = check_drift(
        manifest_intents={i for p in installed_packages for i in p.handled_intents},
        claimed_intents=set(registry.claimed_intents()),
        seeded_intents={i for p in installed_packages for i in p.intents},
        db_intents=await _seeded_intent_classes(),
    )

    if report.fatal:
        # Manifests and tasks ship in the same build from the same repo. If they
        # disagree, no environment explains it and booting anyway would serve
        # patients from a configuration nobody intended.
        raise PackageDrift(
            f"installed packages and registered tasks disagree: {report.as_dict()}"
        )

    if report.database_drift:
        logger.error(
            "intent_vectors is out of step with the installed packages — re-run the "
            "intent seeder. orphaned=%s missing=%s",
            sorted(report.orphaned_in_db),
            sorted(report.missing_from_db),
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await pool.open(wait=True, timeout=15)
    await _check_package_drift()
    sweeper = asyncio.create_task(_sweeper())
    logger.info(
        "agent-core up transports=%s packages=%s claimed_intents=%d tasks=%s",
        list(transports),
        [p.name for p in installed_packages],
        len(registry.claimed_intents()),
        [t.name for t in registry.tasks],
    )
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await asyncio.gather(
            waha.aclose(),
            classifier.aclose(),
            retrieval.aclose(),
            handoff_client.aclose(),
            return_exceptions=True,
        )
        await pool.close()


app = FastAPI(title="NutriWhite Brain — agent-core", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "agent-core"})


@app.post("/webhooks/waha")
async def waha_webhook(request: Request) -> Response:
    body = await request.body()

    if not waha.verify(body, request.headers):
        raise HTTPException(status_code=401, detail="Invalid or missing HMAC signature")

    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    event = waha.normalize(raw)
    if event is None:
        return Response(status_code=204)

    # Durable before acknowledged. Returning 200 for anything not yet persisted is
    # how a message gets lost with no record it ever arrived.
    row_id = await inbox.record(event)
    if row_id is None:
        return Response(status_code=200)

    _spawn(row_id, event)
    return Response(status_code=200)


# -- Admin --------------------------------------------------------------------

@app.post("/admin/handoff/resume")
async def admin_resume(request: Request) -> JSONResponse:
    data = await request.json()
    phone = data.get("contact_phone", "")
    if not phone:
        raise HTTPException(status_code=400, detail="contact_phone required")
    return JSONResponse(await handoff_client.resume(phone))


@app.get("/admin/tasks")
async def admin_tasks() -> JSONResponse:
    """
    What is installed, and whether it agrees with the database right now.

    The drift report is recomputed per request rather than cached from boot —
    `intent_vectors` changes underneath a running process every time the seeder
    runs, which is exactly the window in which you want to look.
    """
    tasks = [{"name": t.name, "intents": sorted(t.handled_intents)} for t in registry.tasks]
    packages = [
        {
            "name": p.name,
            "version": p.manifest.version,
            "task_name": p.manifest.task_name,
            "seeded_intents": len(p.intents),
            "synthetic_intents": sorted(p.manifest.synthetic_intents),
        }
        for p in installed_packages
    ]
    report = check_drift(
        manifest_intents={i for p in installed_packages for i in p.handled_intents},
        claimed_intents=set(registry.claimed_intents()),
        seeded_intents={i for p in installed_packages for i in p.intents},
        db_intents=await _seeded_intent_classes(),
    )
    return JSONResponse({"tasks": tasks, "packages": packages, "drift": report.as_dict()})
