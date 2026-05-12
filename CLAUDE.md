# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A production-safe scaffold for **NutriWhite's WhatsApp customer service agent** ("Gutty"). The agent runtime lives on an Ubuntu host as **OpenClaw**; this repo is the **business backend** plus the **OpenClaw plugin** that gives the agent its narrow tool surface. The design intentionally keeps company knowledge, customer state, and tool policy in three separable services so each can be hardened independently.

## Common commands

```bash
# Local stack (Postgres + RAG API + CRM adapter)
docker compose up --build postgres rag-api crm-adapter

# Ingest knowledge from knowledge/raw/ into Postgres (one-shot)
docker compose run --rm ingest-worker python -m company_agent.ingest_worker.main sync

# Tests (pytest, src/ on pythonpath via pyproject.toml)
pip install -e ".[dev]"
pytest
pytest tests/test_search.py::test_reciprocal_rank_fuse_merges_rankings

# Lint
ruff check .

# Model eval harness (compares Haiku 4.5 / Sonnet 4.6 / GPT-5 / Gemini 3 against NutriWhite cases)
pip install -e ".[eval]"
python -m eval.run_eval --models haiku-4.5
python -m eval.run_eval --models haiku-4.5,gemini-3-flash,gpt-5-mini

# Smoke tests (read .env from project root automatically)
python scripts/zoho_smoke_test.py     # verifies Zoho OAuth + COQL against sandbox
python scripts/model_smoke_test.py    # sends "Hola" to each model
python scripts/openclaw_pending_messages.py   # scans the message journal for unanswered WhatsApp messages
```

## Architecture: the three-service split

OpenClaw is the agent runtime, **not** a business backend. The agent reaches business systems only through narrow HTTP tools defined in [openclaw/plugins/customer-service-tools/index.js](openclaw/plugins/customer-service-tools/index.js). Those tools call two FastAPI services:

- **[rag-api](src/company_agent/rag_api/)** (port 8081) — hybrid retrieval over `knowledge_chunks` in Postgres. Combines lexical (Postgres `tsvector` + `websearch_to_tsquery`) and semantic (`pgvector` cosine) results via **reciprocal-rank fusion** (`rrf_k=60`) in [search.py:79](src/company_agent/rag_api/search.py:79). Semantic retrieval is gated on `EMBEDDING_PROVIDER=openai`; lexical works without an API key.
- **[crm-adapter](src/company_agent/crm_adapter/)** (port 8082) — `MockCrmAdapter` for local dev, `ZohoCrmAdapter` for prod. Switched by `CRM_PROVIDER` env var in [main.py:_build_adapter](src/company_agent/crm_adapter/main.py). Both implement the same `BaseCrmAdapter` interface.
- **[ingest-worker](src/company_agent/ingest_worker/)** — one-shot CLI (not a long-running service). Walks `knowledge/raw/`, chunks via [chunk_markdown](src/company_agent/common/text.py) (1200-char chunks, 180-char overlap), embeds (OpenAI 1536-dim), upserts on `source_uri`. Deletes and re-inserts chunks per document on each sync.

Both API services require the shared `INTERNAL_API_KEY` via `X-Internal-API-Key` header — enforced by [require_internal_api_key](src/company_agent/common/auth.py). The OpenClaw plugin sets this header on every call. The plugin also **rejects non-loopback URLs** ([index.js:localHttpBaseUrl](openclaw/plugins/customer-service-tools/index.js)) — services are expected to be reachable only over `127.0.0.1` on the OpenClaw host.

## Two retrieval paths: deterministic FAQ vs `kb_search`

The plugin exposes both kinds of "knowledge" tools:

- **`kb_search`** — calls `rag-api` for hybrid retrieval. Used for anything off the common path.
- **`faq_location` / `faq_services` / `faq_consultation_plans` / `faq_payment_methods`** — return **hardcoded** Spanish answers inline from [index.js](openclaw/plugins/customer-service-tools/index.js). No retrieval, no LLM round-trip. These exist because they're the highest-frequency questions and we want zero latency / zero hallucination risk on prices and plan details.

If you edit FAQ wording, edit the strings in `index.js` directly — they are not sourced from `knowledge/raw/` at runtime. The agent skill ([openclaw/skills/customer-service-policy/SKILL.md](openclaw/skills/customer-service-policy/SKILL.md)) tells the model which path to prefer for which question shape.

## Zoho CRM module mapping

The Zoho adapter ([zoho_client.py](src/company_agent/crm_adapter/zoho_client.py)) maps NutriWhite-specific Zoho modules:

- `Contacts` → `CustomerProfile` (lookup by phone/id/email; phone uses **last-9-digits LIKE match** because WhatsApp E.164 and Zoho's stored format diverge — see `phone_search_suffix`)
- `Deals` (Tratos) → `DealRecord`, joined on `Contact_Name`
- `Consultas` (custom module) → `ConsultaRecord`, joined on `Comunidad_NW`
- `Examenes` (custom module) → `ExamenRecord`, joined on `Comunidad_NW`
- `Notes` on a Contact = the **handoff/ticket-draft signal**. There is no separate ticketing module; a human asesora picks up the conversation by seeing a new Note in the CRM.

Reads use **COQL** (`/crm/v8/coql`). Writes (Notes only) use REST. Token refresh is cached in [ZohoTokenManager](src/company_agent/crm_adapter/zoho_client.py) and retries once on 401.

## Agent policy lives in two places (both read by OpenClaw)

- [openclaw/skills/customer-service-policy/SKILL.md](openclaw/skills/customer-service-policy/SKILL.md) — full Gutty persona, hard handoff triggers, retrieval query guidance.
- [openclaw/workspace/AGENTS.md](openclaw/workspace/AGENTS.md) — workspace-level system prompt (shorter, runtime-loaded).

When changing agent behavior, update both — they reinforce each other but are loaded in different OpenClaw contexts. Tool descriptions in [openclaw/plugins/customer-service-tools/index.js](openclaw/plugins/customer-service-tools/index.js) are also part of the policy surface (the model uses descriptions to decide when to call a tool); they're written in Spanish on purpose.

## Postgres schema is bootstrapped, not migrated

[sql/001_init.sql](sql/001_init.sql) runs once via `docker-entrypoint-initdb.d/`. No migration tool. Schema changes for production require manual coordination. Indexes: GIN on `search_tsv` for FTS, HNSW (cosine) on the 1536-dim `embedding` column. The chunk's `search_tsv` is a `GENERATED ALWAYS AS` column — do not insert into it.

## OpenClaw deployment posture

OpenClaw runs **on the Ubuntu host** (not in Compose) via `systemd` + Node 24. The plugin is installed locally:

```bash
openclaw plugins install ./openclaw/plugins/customer-service-tools
openclaw gateway restart
```

The plugin expects `RAG_API_URL`, `CRM_ADAPTER_URL`, and `INTERNAL_API_KEY` in the OpenClaw host environment. Tool allow/deny policy is documented in [docs/openclaw-setup.md](docs/openclaw-setup.md) — start from `profile: minimal` and the explicit allowlist there. **Do not** expose `group:runtime`, `group:fs`, `browser`, `web_search`, or `web_fetch` to the customer-facing agent.

The [openclaw/hooks/nw-message-journal](openclaw/hooks/nw-message-journal/) hook appends every `message:received` / `message:sent` event to `/root/nw-agent/runtime/openclaw-message-journal.jsonl` so [scripts/openclaw_pending_messages.py](scripts/openclaw_pending_messages.py) can flag missed replies.

## Eval harness

[eval/run_eval.py](eval/run_eval.py) loads cases from `seeds.yaml`, runs them against each model in `MODEL_REGISTRY` (Anthropic/OpenAI/Google SDKs), and writes JSONL to `eval/results/<timestamp>/<model>.jsonl`. **No tool calls** — Phase 1 evaluates raw response quality (Spanish naturalness, persona match, whether the model says it would hand off, hallucination). Results dir is gitignored. The harness loads `.env` itself with a custom path resolver (it does NOT use `python-dotenv`).
