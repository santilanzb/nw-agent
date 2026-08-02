# R5 — Orchestration core stress-test (Cerebro Gutty v3, 2026-07-08)

Note: the launcher's brief path resolved to `undefined`; scope reconstructed from the R5 task text + repo (CLAUDE.md, `src/company_agent/agent_core/`). Flagging so the orchestrator can re-inject the brief if needed.

## 0. Current state (read from repo)

- `src/company_agent/agent_core/fsm.py` — TurnFSM: per-turn pipeline (dedup → group/DM → handoff-mute → classify → task → side-effects → send → turn_log). ~310 lines, readable, owns its control flow.
- `src/company_agent/agent_core/tasks/base.py` — `TaskModule` Protocol + `TaskRegistry`: linear list scan, intent → first module whose `handled_intents` frozenset matches; default = first registered.
- Grep for `cron|scheduler|proactive|cadence` in `src/` → **no hits**. Proactive cadences and multi-day sagas are 100% greenfield; nothing in the current core can hold state across turns except the Postgres handoff table.
- Latent durability gaps already visible in fsm.py:
  - Dedup is an in-memory `OrderedDict` (`_SEEN`, max 10k) — wiped on every container restart; WAHA webhook redelivery after a deploy = duplicate replies.
  - Handoff-create failure is logged and swallowed (`_fire_handoff`, ~line 228) — fine for handoff, disqualifying for autonomous CRM writes.
  - Turn log is fire-and-forget `asyncio.create_task` — lost on crash.
  - WAHA send: 3 in-process retries, then give up; no durable outbox.

## 1. What production systems actually run on in 2026 (evidence per candidate)

### Hand-rolled FSM / own loop
- 12-factor agents (HumanLayer): "own your control flow"; "most really strong founders are rolling the stack themselves, and there aren't a lot of frameworks in production customer-facing agents." https://github.com/humanlayer/12-factor-agents , factor-08. Echoed by https://starlog.is/articles/ai-agents/humanlayer-12-factor-agents/ ("production LLM apps are mostly deterministic code") and the 80%-quality-ceiling argument (frameworks hide prompts/state/control loop).
- Anthropic "Building Effective Agents": "start by using LLM APIs directly: many patterns can be implemented in a few lines of code"; frameworks "create extra layers of abstraction that can obscure the underlying prompts and responses." https://www.anthropic.com/research/building-effective-agents
- Verdict on where it cracks (honest answer): **not at TaskModule count**. The registry + embedding classifier routes on intent, so 10→20→50 disjoint modules scale linearly (the risk is intent-overlap/ambiguity in the classifier, a data problem, not a code problem; a dict lookup replaces the list scan at ~20 modules). It cracks on **time and exactly-once**: (a) "follow up in 3 days if silent" / weekly cadences need durable timers; (b) multi-turn slot-filling sagas (exam budget → payment proof → ticket) need per-conversation persistent state; (c) autonomous CRM writes need idempotent, crash-recoverable steps; (d) every hand-rolled saga re-implements retry/timer/idempotency, and the test matrix explodes with cross-cutting concerns, not with module count. That is durable-execution territory, not agent-framework territory.

### LangGraph
- Vendor-cited production: Uber, LinkedIn, AppFolio, Elastic; 1.0 stable late 2025. https://docs.langchain.com/oss/python/langgraph/case-studies , https://www.langchain.com/langgraph (vendor marketing — discount).
- Durability: PostgresSaver checkpointer + interrupts for human-in-the-loop; multi-day pause possible via checkpoint + resume. https://docs.langchain.com/oss/python/langgraph/durable-execution (fetched; docs are thin on multi-day semantics).
- Failure/friction reports: checkpoint serialization footguns (Pydantic v2 custom serializers, numpy → silent failures surfacing only on resume), awkward cross-graph state sharing, "debugging story still worse than a custom loop," frequently overkill. https://www.kalviumlabs.ai/blog/langgraph-vs-langchain-production/ , https://aerospike.com/blog/langgraph-production-latency-replay-scale/ (secondary sources; UNVERIFIED first-hand).
- Fit here: would replace a working 300-line FSM with a graph DSL + checkpointer that still doesn't give cron/cadence scheduling. Adds an abstraction layer the team must debug through. Middling.

### OpenAI Agents SDK
- Real deployments exist (Coinbase AgentKit prototype; one healthcare-records pilot). https://openai.com/index/new-tools-for-building-agents/ , https://team400.ai/blog/2026-03-openai-agents-sdk-practical-guide
- OpenAI-model-centric; Gutty runs on Anthropic (`agent_core/llm/anthropic.py`, Langfuse-traced). Fewer integrations, less battle-testing vs LangChain per third-party reviews. Disqualified by model lock-in + no durability/scheduling story for multi-day sagas.

### Claude Agent SDK
- 2026 default for long-running *coding/computer* agents; harness = agent loop + sessions + permissions + hooks; multi-context-window patterns per Anthropic. https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents , https://code.claude.com/docs/en/agent-sdk/overview
- From June 15, 2026 SDK usage metered separately (per-token billing pressure). https://support.claude.com/en/articles/15036540 (UNVERIFIED detail, secondary source).
- Fit: it is an *execution harness for one autonomous agent*, not a webhook-driven multi-conversation orchestrator. Plausible later as the inner engine for the "autonomous CRM operator" function (F-scope) inside a durable step; wrong shape for the core.

### Mastra
- 1.0 Jan 2026, 300k weekly npm downloads, Replit/PayPal/SoftBank logos; workflows + memory + evals bundled. https://mastra.ai/ , https://github.com/mastra-ai/mastra
- TypeScript-native. Team's backend is Python/FastAPI (rag-api, crm-adapter, agent-core). Adopting it = rewriting the core in TS or running a second runtime. Disqualified on stack fit, not on quality.

### Temporal
- The scale-proven answer: $300M raise at $5B (Feb 2026), 380% YoY revenue, 9.1T lifetime actions; explicit AI-agent positioning; multi-day/multi-month workflows are its core competence. https://temporal.io/blog/replay-2026-product-announcements , https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal (vendor).
- Cloud is HIPAA-compliant (BAA available). https://temporal.io/blog/temporal-cloud-is-now-hipaa-compliant ; Essentials from ~$100/mo, $50/M actions. https://temporal.io/pricing
- Burden: self-host = multi-service cluster (frontend/history/matching + Cassandra or scaled Postgres); third-party TCO analyses put self-host at $2.5–4.5k/mo infra+ops and recommend Cloud below ~30–50M actions/mo; one mid-stage SaaS abandoned self-host because on-call couldn't absorb it. https://automationatlas.io/guides/temporal-cloud-vs-self-hosted-2026/ (UNVERIFIED numbers, single secondary source).
- Fit: 500–2000 leads/mo is maybe 50–200k actions/mo — three orders of magnitude under Temporal's sweet spot. Cloud also moves workflow payloads (patient phone/context) to a third party unless you wire the encrypting data converter — extra work under PHI constraints. Overkill now.

### DBOS Transact
- Library-only durable execution: "no separate orchestration server and no infrastructure required besides Postgres"; step results checkpointed transactionally; replay from last committed step; durable queues with flow control; >40k steps/s on Postgres alone; Conductor control plane optional and "never involved in workflow execution." https://docs.dbos.dev/architecture (fetched directly).
- Cron-scheduled workflows via `@DBOS.scheduled` (6-field cron), durable sleep, queue dedup/rate-limit/priority. https://docs.dbos.dev/python/tutorials/scheduled-workflows , https://github.com/dbos-inc/dbos-transact-py
- Honest limits: steps are **at-least-once** (no automatic rollback of external side effects; a step may re-run) — WAHA sends and Zoho writes need idempotency keys or check-then-act guards; queue throughput bounded by Postgres. https://github.com/dbos-inc/dbos-transact-py
- Third-party positioning: "most backend services in 2026 can ship durable execution with DBOS and come back to Temporal if and when they hit the wall." https://www.tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution , https://devstarsj.github.io/2026/04/03/durable-execution-temporal-restate-dbos-distributed-workflows-2026/
- Fit: **best**. Same process (FastAPI), same language (Python), same store (the Postgres already running in compose, already holding handoff state + turn_log). PHI never leaves owned infra. License believed MIT (UNVERIFIED — confirm before commit); company viability is a real open question (small vendor).

### Restate
- Single self-hosted binary, no extra DB/worker queue; durable sessions keyed per conversation; human-approval pauses that survive crashes; push model suits webhooks; Pydantic AI integration exists. https://docs.restate.dev/use-cases/ai-agents , https://pydantic.dev/articles/restate-durable-execution-pydanticai , https://www.restate.dev/
- Fit: second-best. Elegant, but introduces a *new stateful runtime component* (its own journal store) next to Postgres, a smaller community, and (UNVERIFIED) a BSL-style server license. For a 1–3 person team, one database to back up beats two.

## 2. Synthesis — what the scope actually decomposes into

| Workload | Current FSM | What it needs |
|---|---|---|
| Reactive chat turn (<5s) | Works today | Keep; fix durable dedup (Postgres inbox table w/ unique event_id) |
| Proactive weekly cadences | Absent | Durable cron + per-lead saga state + idempotent sends |
| Multi-day sagas (exam budget → proof → ticket) | Absent | Durable timers, resumable per-conversation state |
| Autonomous CRM operator | Fire-and-forget writes | Exactly-once-ish steps, audit trail, approval gates |
| Voice seam (future) | `normalize_waha_event` already isolates transport | Keep orchestration transport-agnostic; voice = new adapter (Pipecat/LiveKit class) calling same turn entrypoint — no framework implication today |

The 2026 production pattern at this scope is **not** "adopt an agent framework." It is: own a thin deterministic loop for the conversational turn (12-factor / Anthropic guidance), and delegate *time + retries + exactly-once* to a durable-execution layer. Agent frameworks (LangGraph/Mastra/SDKs) solve LLM-loop composition, which is not where this system hurts; durable execution (Temporal/DBOS/Restate) solves exactly the three missing workloads.

## 3. Recommendation

Keep the hand-rolled TurnFSM as the reactive router (it is an asset, not debt). Add **DBOS Transact (Python)** inside agent-core for: proactive cadences (`@DBOS.scheduled`), multi-day sagas (durable sleep + queues, keyed by phone-hash), and CRM-operator workflows (checkpointed steps + idempotency keys on Zoho/WAHA calls). Move dedup and outbound sends to Postgres-backed inbox/outbox tables (DBOS gives most of this for free). Re-evaluate Temporal Cloud (HIPAA BAA exists) only if saga complexity or team size outgrows the library model. Do not adopt LangGraph/OpenAI Agents SDK/Mastra for the core; consider Claude Agent SDK later strictly as the inner engine of the autonomous CRM operator, wrapped in a durable step.

## 4. Open questions

1. DBOS Transact license (MIT?) and vendor viability without Conductor — verify before committing.
2. Restate server license (BSL?) — if DBOS is rejected, this changes the fallback.
3. WAHA send idempotency: no idempotency-key support known → at-least-once steps can double-send; need message-content dedup or send-log guard.
4. Is HIPAA the actual binding legal regime for NutriWhite (Venezuela/LatAm patients) or an internal proxy policy? Changes whether Temporal Cloud/managed options are even on the table.
5. Claude Agent SDK separate metering (June 2026) — cost model if used for CRM-operator tasks.
