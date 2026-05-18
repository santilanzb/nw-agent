# NutriWhite Brain — Execution Status

> **For:** planner / next executor session
> **Last updated:** 2026-05-18
> **Executor:** Claude Sonnet 4.6 (build session)
> **Plan:** `docs/nutriwhite-brain-plan.md`
> **Droplet:** `165.227.73.90` · `ssh root@165.227.73.90`

---

## Overall position

Phase 1 is **97% complete**. Every service is deployed and verified. One manual step remains: a human must scan a QR code with a TEST WhatsApp number to activate the WAHA session. That scan cannot be done by an agent — it requires a phone.

After the scan, the executor runs `python scripts/smoke_test_phase1.py` on the droplet. If 5/6 (or 6/6) tests pass, Phase 1 is accepted and the planner can greenlight Phase 2.

---

## Phase 1 status — task by task

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `sql/004_brain.sql` applied to prod Postgres | ✅ Done | `turn_log`, `patient_episodes`, `episode_summaries`, `patient_facts`, `learning_queue` all exist |
| 2 | `langfuse` DB created in Postgres | ✅ Done | Schema migrated by Langfuse on first start |
| 3 | `agent-core` code written | ✅ Done | FSM, HMAC verify, CustomerServiceTask, LLM client, turn_log writer |
| 4 | `docker-compose.yml` updated (waha + agent-core + langfuse) | ✅ Done | 3 new services |
| 5 | All services deployed to droplet | ✅ Done | See "Live service state" below |
| 6 | WAHA healthcheck working | ✅ Done | Took 4 iterations (see "Deviations") |
| 7 | Langfuse API keys created | ✅ Done | Inserted directly into Postgres (see "Deviations") |
| 8 | `agent-core` `/health` returns OK | ✅ Done | `{"status":"ok","service":"agent-core"}` |
| 9 | **WAHA QR scan — TEST phone pairing** | 🔴 **BLOCKED** | Requires human with phone. See "Blocker" section. |
| 10 | Set `HANDOFF_TEAM_GROUP_JID` in `.env` | ⏳ After scan | Get JID from WAHA after pairing |
| 11 | Run Phase 1 smoke tests (6 turns) | ⏳ After scan | `python scripts/smoke_test_phase1.py` on droplet |
| 12 | Verify Langfuse traces for LLM turns | ⏳ After smoke tests | `http://165.227.73.90:3001` |

---

## Live service state (as of 2026-05-18)

```
nw-waha           Up  (healthy)  :3000   — session created, awaiting QR scan
nw-agent-core     Up             :8083   — health OK, no turns processed yet
nw-langfuse       Up             :3001   — project "agent-core" created, keys active
cs-agent-rag-api  Up             :8081   — unchanged from pre-pivot
cs-agent-crm-adapter Up          :8082   — unchanged from pre-pivot
cs-agent-postgres Up  (healthy)  :5432   — all tables present
```

OpenClaw (pre-pivot runtime) is **still running** on the droplet via systemd. It is the current production agent. WAHA is not yet receiving production WhatsApp messages.

---

## The one blocker

**WAHA QR scan** — a human must:

1. Open `http://165.227.73.90:3000/dashboard`
2. Login: user `admin`, password = `WAHA_DASHBOARD_PASSWORD` from `/root/nw-agent/.env` on the droplet
3. Start the `default` session
4. Scan the QR code with a **TEST phone** (any WhatsApp number that is NOT `+58 412 325 1172`)
5. Confirm session status flips to `WORKING`

The QR code expires in ~60 seconds. If it expires before scanning, stop and restart the session via the dashboard.

**Why this can't be automated:** WAHA's QR code must be scanned by a real WhatsApp-linked phone. There is no programmatic bypass.

---

## Deviations from plan

These are places where the plan's instructions were wrong or underspecified. A planner should update the plan if re-running this phase.

| # | Plan said | Reality | Impact |
|---|---|---|---|
| D1 | `WAHA_API_KEY_PLAIN: ${WAHA_API_KEY}` | Current WAHA ignores `WAHA_API_KEY_PLAIN`. Must use `WAHA_API_KEY`. WAHA generates and logs a new key on every restart if the var is absent. | **Fixed** in `docker-compose.yml`. Plan doc updated. |
| D2 | Healthcheck: `wget -qO- http://127.0.0.1:3000/api/ping` | `/api/ping` returns 404 in WAHA Core. Use `/api/sessions`. Also: `CMD` array form doesn't expand `$WAHA_API_KEY` — must use `CMD-SHELL`. | **Fixed** in `docker-compose.yml`. Plan doc updated. |
| D3 | `depends_on: waha: condition: service_healthy` | agent-core's WAHA dependency should be `service_started`, not `service_healthy`. The healthcheck requires auth; agent-core works fine as soon as WAHA's HTTP port is open. | **Fixed** in `docker-compose.yml`. |
| D4 | "Set Langfuse keys after first admin login" | Langfuse v2 self-hosted has no web signup API. Account, org, project, and API keys must be seeded directly into Postgres via Python + psycopg (bcrypt for `hashed_secret_key`, SHA-256 for `fast_hashed_secret_key`). | **Done** manually. Langfuse credentials in droplet `.env`. |
| D5 | Plan says Langfuse is `(Phase 4)` in the architecture diagram | Per §11.3 resolved decision: Langfuse ships in Phase 1 alongside agent-core. The architecture diagram comment was inconsistent. | Minor — diagram label only. No code impact. |

---

## Langfuse credentials (droplet only)

| Field | Value |
|---|---|
| Dashboard URL | `http://165.227.73.90:3001` |
| Admin email | `admin@nutriwhite.local` |
| Admin password | `NWBrain2026!` |
| Project | `agent-core` |
| Public key | `pk-lf-FDYPt8YUi2j5_NKRTWHRg83bTBA` |
| Secret key | in droplet `.env` as `LANGFUSE_SECRET_KEY` |

---

## Next ordered actions (for planner → executor)

### Immediate (unblocks smoke tests)
1. **[HUMAN]** Scan WAHA QR with test phone — instructions in "Blocker" section above
2. **[EXECUTOR]** After scan: `curl -s http://localhost:3000/api/sessions/default -H 'X-Api-Key: ...' | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])'` → confirm `WORKING`
3. **[EXECUTOR]** Get team group JID: send a message from the test phone's team group and watch WAHA events, OR skip this and set `HANDOFF_TEAM_GROUP_JID=` (empty) — test 4 will be skipped, other 5 will still run
4. **[EXECUTOR]** Run smoke tests: `python scripts/smoke_test_phase1.py` (from droplet or locally with correct env vars)
5. **[EXECUTOR]** Verify Langfuse traces at `http://165.227.73.90:3001` for tests 5 and 6 (LLM-using turns)
6. **[EXECUTOR]** Report: 6 smoke test outputs + Langfuse trace URLs → Phase 1 accepted

### After Phase 1 acceptance
7. **[PLANNER]** Decide: proceed to Phase 2 (graph layer) or do Stage 3 cutover first?
   - The plan recommends smoke tests pass → cutover → then Phase 2
   - Cutover replaces OpenClaw with WAHA on the production Gutty number (`+58 412 325 1172`)
   - Estimated downtime: 5–15 minutes during QR scan
   - Full cutover procedure in `docs/nutriwhite-brain-plan.md` §9 Stage 3

---

## Phase 2–4 status

| Phase | Status | Prerequisite |
|---|---|---|
| Phase 2 — Graph layer (AGE + Zoho bootstrap) | 🔵 Not started | Phase 1 accepted |
| Phase 3 — Episodic memory + patient-aware composition | 🔵 Not started | Phase 2 complete |
| Phase 4 — Self-learning loop + review queue | 🔵 Not started | Phase 3 complete |

Phase 2 Day 1 requires a custom Postgres Docker image (pgvector + Apache AGE compiled for PG16). The plan §4 has the full schema and bootstrap strategy.

---

## Key files for a new executor session

```
docs/nutriwhite-brain-plan.md   — full architecture + phase specs
docs/brain-status.md            — this file (current state)
CLAUDE.md                       — repo overview + Brain section
scripts/smoke_test_phase1.py    — Phase 1 acceptance test
src/company_agent/agent_core/   — all Brain code
sql/004_brain.sql               — Brain tables (applied)
docker-compose.yml              — all services (current, corrected)
.env (droplet only)             — all secrets
```
