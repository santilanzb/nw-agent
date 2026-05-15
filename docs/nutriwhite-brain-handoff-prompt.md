# NutriWhite Brain — Handoff Prompt for the Pivot-Planning Session

This file is for the user's reference. The actual prompt to paste into a fresh Claude Code session is the "PROMPT" block below. The planner agent should read this doc plus the reading list it points at and then produce `docs/nutriwhite-brain-plan.md`.

**Recommended session setup:** Opus 4.7 (planning needs synthesis), high effort, on the **Windows working copy** (planner doesn't need droplet access — this is a writing task). Alternatively a fresh Sonnet 4.6 high-effort session is acceptable if Opus is unavailable.

**What the planner will produce:** a self-contained build plan at `docs/nutriwhite-brain-plan.md`. A subsequent build session will execute it.

**What the planner will NOT do:** write code, modify backend services, deploy anything, or send WhatsApp messages.

---

## PROMPT

```
You are taking over the NutriWhite WhatsApp agent project at a strategic pivot point. Your job is to write `docs/nutriwhite-brain-plan.md` — a self-contained architecture + build plan for a separate Sonnet session to execute. You do not write code in this session, only the planning document.

## Context — read these before drafting

Repo files (in this order):
- `CLAUDE.md` — repo overview
- `docs/architecture-diagrams.md` — system overview (current state) + reliability scorecard
- `docs/intent-router-plan.md` — Phase 1 plan that shipped (classifier at 99.1%)
- `docs/agent-core-plan.md` — Phase 2 plan (OpenClaw hook approach)
- `docs/hook-fix-before-dispatch-plan.md` — Phase 2 retrofit (correct hook name)
- `docs/phase-3-team-push-plan.md` — Phase 3 attempt (team-group push)

External, optional but useful:
- WAHA docs at https://waha.devlike.pro/ — the WhatsApp HTTP API we are migrating to
- Apache AGE docs at https://age.apache.org/age-manual/master/ — Postgres graph extension (one candidate for the graph layer)

## Current state (2026-05-15)

What is rock-solid and must be reused as-is:
- Postgres + pgvector (`knowledge_chunks`, `intent_vectors`, `handoff_state`)
- `rag-api` (FastAPI) with `/v1/retrieve` and `/v1/classify_intent` — 99.1% intent eval accuracy
- `crm-adapter` (FastAPI) with handoff lifecycle (pending → claimed → resumed → expired) and Zoho integration
- `ingest-worker` and `intent_seeder` CLI tools
- All knowledge seeds, intent seeds, and the eval harness
- Zoho COQL reads and Notes writes

What has been brittle and is being replaced:
- OpenClaw v2026.5.7 as the agent runtime and WhatsApp transport. Specific failure modes encountered across multiple sessions: plugin loader silently dropping our plugin due to a duplicate-id cache, the `inbound_claim` hook never firing (the correct hook turned out to be `before_dispatch`), the `allowConversationAccess` permission flag being a privacy gate that emptied `event.content`, `channels.whatsapp.groups.*` rejecting `allowFrom` silently with `must NOT have additional properties`, and the WhatsApp watchdog forcing reconnects after long quiet periods which puts the connector into a re-auth loop. Each fix has been correct but the surface area is too large and the half-life of "working" is roughly one restart.

The decision the user has made: pivot the orchestration and transport layers to a custom Python service backed by WAHA for WhatsApp. Keep everything below the orchestration layer.

## Architectural vision: "NutriWhite Brain"

The user's framing — and this is core to the plan — is that NutriWhite needs a brain, not just a chatbot. The brain knows the domain (people, plans, services, supplements, conditions, history, policies) and can be assigned tasks. Customer service on WhatsApp is task #1. Future tasks (patient follow-up, exam-result processing, inventory queries, appointment reminders, etc.) plug in as task modules sharing the same brain.

The brain is hybrid:

1. Vector knowledge — semantic retrieval over approved content. Already built (`knowledge_chunks`, `intent_vectors`).
2. Graph knowledge — entities and their relationships. NEW. NutriWhite's domain is intrinsically relational: a Contact has a Plan, a Plan has Consultas, a Consulta has an Especialista, a Patient has Conditions, Conditions map to recommended Supplements, etc. Vector retrieval alone cannot answer "which especialistas are best for digestive conditions in patients without active examenes." Graph traversal can.
3. Episodic memory — per-patient conversation history, preferences, and learnings across sessions. NEW. Patient turns are not stateless; the brain remembers prior context.
4. Working memory — per-turn state (handoff state, claim state, conversation context). Already partly built (`handoff_state`).
5. Self-learning — every interaction feeds back. Misclassifications become new intent seeds. Novel entities become new graph nodes. The classifier and the graph grow from production traffic.

Routing posture: deterministic-first. Known high-confidence intents skip the LLM. The LLM is invoked only for composition, ambiguous routing, novel reasoning over graph results, and patient-specific compositions where canned text would feel cold.

Extensibility posture: task-pluggable. A new task is a Python module that declares the intents it owns, the graph entities it touches, and the response composition strategy.

## What the plan document must cover

Numbered list. Cover all of these. Skipping any is unacceptable.

1. Architecture overview — Mermaid diagram, named components, data flow, what is new vs reused. Distinguish clearly between the brain layer and the task layer.

2. Transport replacement: WAHA
   - Why WAHA (vs Meta Cloud API vs Twilio vs whatsapp-web.js vs Baileys-direct). Honest tradeoffs.
   - WAHA Docker Compose service config; pairing flow; webhook receiver setup.
   - Outbound send (REST). How patient replies and team-group push both flow.
   - Plan to migrate WhatsApp pairing from OpenClaw to WAHA without losing chat continuity (or accept short pairing-window downtime).

3. Agent-core orchestration service
   - Tech stack. Recommend FastAPI + a small hand-written state machine, or LangGraph if the planner justifies the dependency. Default to hand-written unless LangGraph adds clear value the planner can name.
   - The orchestration state machine: inbound → check_handoff_state → classify_intent → optional graph_lookup → dispatch → optional LLM composition → outbound.
   - LLM integration via Anthropic SDK directly. Use `tool_choice` for forced tool calls when calling Claude for ambiguous routing. Default model: claude-sonnet-4-6 with low effort thinking for composition turns; haiku for cheap dispatch.
   - Per-turn timing budget and retry/circuit-breaker policy.
   - Observability: structured logs at minimum; recommend Langfuse self-hosted for full LLM-call tracing.

4. Graph layer
   - Why a graph layer is correct for NutriWhite specifically. Concrete query examples that vector retrieval cannot answer well.
   - Database choice. Default to Apache AGE (Postgres extension, keeps the stack single-DB). Justify any other choice with operational tradeoffs.
   - Initial schema: nodes (Contact, Plan, Consulta, Examen, Especialista, Condition, Supplement, Service, Location, Operator) and edges (HAS_PLAN, ASSIGNED_TO, RECOMMENDED_FOR, LOCATED_AT, etc.). The schema must be derived from existing Zoho data not invented.
   - Query interface from agent-core (Cypher via AGE, or a small Python wrapper). Worked example: "given the patient's contact_id, return the active Plan, the next scheduled Consulta with its Especialista, and any pending Examenes."
   - Bootstrap strategy: how to seed the graph from Zoho. Ongoing sync model (poll vs Zoho webhooks vs on-demand fetch).

5. Episodic memory
   - Schema per patient: turn log, key facts learned, preferences, language register, prior topics, last successful CTA. Distinguish PII-sensitive fields.
   - Storage layout: Postgres table referencing the same contact_phone key. Vector embedding of summarized turns for semantic recall over long histories.
   - Retrieval strategy: last N raw turns plus k-NN semantic recall over older summaries.
   - Privacy: explicit retention policy. Document which fields are wiped on patient request. Document encryption-at-rest plan if Postgres is on the droplet.

6. Self-learning loop
   - What gets logged on every turn: input text, classified intent, confidence, dispatch decision, tool invoked, LLM call (if any), outcome, patient feedback (implicit: did the conversation continue? did handoff fire?).
   - The loop close mechanism: a daily or weekly job that surfaces misclassifications and low-confidence routes to a review queue. Reviewed items become new intent seeds and trigger a re-ingest. Define this job concretely.
   - The first three concrete "wins" the self-learning loop should produce so the user can measure it: e.g., (a) low-confidence questions about supplements become new seeds within a week, (b) novel patient symptoms get logged as graph entities awaiting review, (c) clarification responses get patterned so similar future asks dispatch cleanly.

7. Task framework
   - The TaskModule interface. What a task module declares: intent ids it handles, graph entities it reads/writes, tools it exposes, response templates.
   - Initial registration of customer-service-task as the first concrete module.
   - Routing model: the brain classifies intent; the intent maps to a task; the task owns the dispatch and composition logic. Tasks are pluggable but the brain owns memory and graph.
   - Sketch two future tasks (e.g., patient-follow-up, exam-result-notification) at the interface level only, not implementation. Just enough to prove the framework holds.

8. What we keep (do not rewrite)
   - Explicit list of files and services that are reused as-is.
   - The reasoning: the backend has been stable through every failure. The brain wraps it; it does not replace it.

9. Migration / cutover plan
   - WAHA Compose service stands up in parallel with OpenClaw still running.
   - agent-core stands up pointing at WAHA's webhook.
   - End-to-end smoke test against a test WhatsApp number routed to WAHA only.
   - Cutover: pair the production Gutty number with WAHA instead of OpenClaw. Estimate ~10 min downtime during pairing.
   - Two-week observation period with OpenClaw fully decommissioned or kept as cold standby.

10. Phased timeline with explicit acceptance criteria
   - Phase 1 (target 2–3 days): WAHA + agent-core skeleton + CS task on existing classifier. Achieves what OpenClaw currently does on a good day, deterministically.
   - Phase 2 (target +5 days): Graph layer bootstrapped from Zoho, agent-core uses it for patient-status intents.
   - Phase 3 (target +7 days): Episodic memory layer. Patient-aware composition.
   - Phase 4 (target +10 days): Self-learning loop. Reviewable misclassification queue. First three concrete wins demonstrated.
   - Phase 5+ (later): Additional task modules.
   - Each phase has a 1-sentence acceptance criterion that is unambiguous.

11. Open decisions for the user — anything that genuinely blocks execution. Examples that may apply: which Anthropic model tier for compositions in production; where to host WAHA's Chromium (same droplet vs separate); whether to add Langfuse for tracing now or defer; retention windows for episodic memory; whether to gate self-learning ingestion on human review or auto-apply with rollback.

12. Reading list for the build agent — files in the repo plus external docs URLs.

13. Anti-scope — explicit list of what is NOT in this plan, to prevent the build session from drifting. E.g., voice channel, multi-tenant clinic support, Spanish↔English translation features, model fine-tuning.

## Constraints

- Do not propose rewriting rag-api, crm-adapter, or any working backend service.
- Do not propose moving away from Postgres unless you can name a specific operational failure in Postgres that the alternative solves.
- Do not propose paid services where a credible self-hostable option exists.
- Default to boring technology. Justify each non-boring choice (LangGraph, Neo4j, Redis, etc.) with a specific reason rooted in NutriWhite's needs.
- The plan must be executable by a fresh Sonnet session reading only the plan, the reading list files, and external docs URLs the plan references. Do not assume the build agent has any context from this planning session.

## Hand-off contract

Commit `docs/nutriwhite-brain-plan.md` and push. In your final message to the user, state:
- Where the plan lives.
- The open decisions in section 11 that need user input before the build session starts.
- The exact first-message prompt the user should paste into the fresh build Sonnet session to kick off Phase 1.
- Estimated total build time across Phases 1–4 based on your scoping.

Do not start the build. Do not modify anything outside the plan document.
```

---

## How to use this

1. Open a fresh Claude Code session in `C:\Users\LANZ\nw-agent`.
2. Set model: `/model claude-opus-4-7` (planning needs strong synthesis; if Opus is locked, use `claude-sonnet-4-6` with high effort).
3. Paste the contents of the `PROMPT` block above verbatim.
4. The planner produces `docs/nutriwhite-brain-plan.md` and reports back with open decisions.
5. After you answer the open decisions, you start a separate Sonnet build session for Phase 1 using the prompt the planner provides.

## Why I'm structuring it this way

- One session writes the plan, a different session builds. Different cognitive modes, different prompts, different model tiers. Keeps each session focused.
- The planner is asked to produce a doc the next session reads with zero conversation context. Forces the plan to be truly self-contained.
- The "anti-scope" section in the plan is the planner's commitment to not building creep. Without it, every section becomes a temptation for the build session to over-engineer.
- The phased timeline with explicit acceptance criteria gives you check-in points and bail-out moments — if Phase 1 doesn't ship in 3 days, we know before sinking a week.
