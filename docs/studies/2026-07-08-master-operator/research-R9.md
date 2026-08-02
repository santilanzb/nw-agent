# R9 — Observability, Evals, Learning (Cerebro Gutty v3 Master Operator)

Date: 2026-07-08. Researcher R9. Brief file was NOT delivered (path resolved to "undefined"); scope taken from tasking: sales-conversation evals, CRM-write correctness evals, review-queue UX for one part-time quality owner, Langfuse vs OTel-native 2026, online LLM-as-judge sampling, frozen-weights learning loops.

---

## 1. Current state (repo ground truth)

- **Langfuse v2 self-hosted** is deployed (`langfuse/langfuse:2`, Postgres-only backend, port 3001) and wired into `agent-core` via the **legacy v2 Python SDK style** (`self._lf.trace(id=turn_id)` / `trace.generation(...)`) in `src/company_agent/agent_core/llm/anthropic.py`. Trace id = turn_id.
- **`turn_log`** (sql/004_brain.sql) already captures per-turn: intent, confidence, decision, dispatch tool+params, task outcome, model, tokens, latency, reply text, `follow_up_within_minutes` (implicit feedback), `handoff_fired`, and a full **review workflow** (`review_status` unreviewed/accepted/rejected/reseed_pending/reseed_done, reviewer, notes) with a partial index on unreviewed rows. Phone is SHA-256 hashed.
- **`learning_queue`** table exists: kinds `reseed | new_intent | new_condition | new_entity | prompt_fix`, statuses pending/approved/rejected/applied.
- **Learning-loop design** (docs/nutriwhite-brain-plan.md §6, resolved decisions): weekly job clusters flagged turns (clarify / fallback_llm / confidence<0.65 / rapid follow-up) by embedding k-NN into a **Markdown review file** (`learning_review/queue/YYYY-WW.md`). **Auto-apply with eval-regression rollback**: reseeds auto-apply at cluster_size≥8 + judged confidence≥0.70, then the eval harness runs; **>2% pass-rate regression triggers automatic git revert** of intent_seeds.yaml. Rate limits: ≤3 reseed + ≤5 new_condition applies per 24h. `new_intent`/`prompt_fix` stay manual. Human gets **undo, not approval**.
- **Eval harness** (`eval/run_eval.py`, 361 lines): `--mode generation` (raw response quality, no tools) and `--mode intent` (classifier correctness vs `expected_intent`, ~99% on seed set). No trajectory/tool-call/CRM-write mode yet.
- CRM writes today are **Notes-only** (handoff signal). v3 Master Operator adds real field writes (exam budgets, tickets) → CRM-write eval becomes a new requirement.

## 2. Langfuse in 2026 — the platform moved out from under this deploy

- **ClickHouse acquired Langfuse on 2026-01-16** (alongside ClickHouse's $400M Series D). Roadmap and MIT license stated unchanged; "remains open source and self-hostable." Sources: https://clickhouse.com/blog/clickhouse-acquires-langfuse-open-source-llm-observability , https://langfuse.com/blog/joining-clickhouse , https://siliconangle.com/2026/01/16/database-maker-clickhouse-raises-400m-acquires-ai-observability-startup-langfuse/
- **All product features went MIT in June 2025** (LLM-as-a-judge managed evaluators, annotation queues, prompt experiments) — but only on **v3 ≥ 3.65.0**. Self-hosting is free with no feature gating. Sources: https://langfuse.com/pricing-self-host , https://github.com/langfuse/langfuse , https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge
- **v3 self-hosted infra is heavy**: requires ClickHouse (≥24.3, UTC, ~2 CPU/8 GiB), Redis/Valkey, and S3-compatible blob store, plus Postgres. Source: https://langfuse.com/self-hosting , https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse , https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v2-to-v3 . Third-party cost estimates for production self-host run $200-800/mo for ClickHouse alone at scale (https://coverge.ai/blog/langfuse-pricing — vendor-adjacent, take as rough); at Gutty volume a single upgraded droplet (8-16 GB) suffices, but it is 3 more containers for a 1-3 person team.
- **v2 is frozen**: v2 SDK "supported for the foreseeable future with critical bug fixes and security patches, but no new features" (https://langfuse.com/docs/observability/sdk/upgrade-path/python-v2-to-v3). Python SDK is now on **v3→v4** upgrade path and is **OpenTelemetry-native** (https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4 , https://langfuse.com/integrations/native/opentelemetry). UNVERIFIED: exact EOL date for v2 server — none published that I could find; treat as maintenance-only.
- **Implication:** the deployed Langfuse v2 can never get the eval features Gutty needs (judge evaluators, annotation queues, code evaluators shipped May 2026 per https://toolbrain.net/blog/langfuse-review-2026/ — secondary source, UNVERIFIED detail). Staying on v2 means Langfuse is a trace viewer only.

## 3. OTel-native alternative: Arize Phoenix

- **Phoenix v17.20.0 (released 2026-07-07)**, license **Elastic License 2.0** — not OSI-open-source but free for internal self-hosted use (restriction is on reselling it as a managed service). Single container (`arizephoenix/phoenix`), UI on 6006, **built-in OTel gRPC collector on 4317**, backed by SQLite or Postgres (can reuse the existing droplet Postgres). Includes eval library (hallucination/QA/relevance/toxicity evaluators), datasets/experiments, human annotation. Sources: https://github.com/arize-ai/phoenix , https://arize.com/docs/phoenix , https://railway.com/deploy/phoenix
- OTel-native means instrumentation written once (OTel GenAI/OpenInference spans) can later point at Langfuse v3, Phoenix, SigNoz, or Grafana without code changes — Langfuse's own v3+ SDK is OTel-based, so the lock-in risk is now low on either side.
- 2026 comparative coverage consistently frames Phoenix as the "self-host-light, evals-included" option vs Langfuse as the "full platform, heavier infra" option: https://www.morphllm.com/comparisons/arize-phoenix-vs-langfuse , https://signoz.io/comparisons/llm-observability-tools/ (both secondary/SEO-grade — directionally consistent with primary docs).

## 4. PHI posture of the options

- Everything self-hosted on the droplet keeps PHI in-house — the decisive constraint. Independent healthcare-focused roundups: "PHI residency requirements often eliminate multi-tenant SaaS; Langfuse's open-source core is one of the few credible self-hosted options" (https://www.confident-ai.com/knowledge-base/compare/best-ai-observability-tools-for-healthcare-companies-2026 — competitor-authored, but the structural point stands).
- **Langfuse Cloud has a HIPAA-ready region requiring an eligible paid plan + signed BAA** (https://langfuse.com/faq/all/fifteen-questions-langfuse-answered). LangSmith BAA = Enterprise tier; Braintrust = commercial/hybrid. All add recurring cost and a data-processor relationship a 1-3 person Venezuelan/US-patient nutrition clinic doesn't need when self-host works. Verdict: cloud eval SaaS rejected.
- Note `turn_log` hashes phones but stores raw `inbound_text`/`reply_text` (free text can contain PHI); Langfuse/Phoenix traces contain full prompts. Any platform choice must stay inside the droplet or the PHI story breaks regardless of vendor.

## 5. Sales-conversation evals (win-rate proxies, tone, claim accuracy)

**Outcome layer (deterministic, from CRM ground truth — no judge needed):**
- Join `turn_log.phone_hash` → Zoho Contacts/Deals: qualification-field completeness, consultation booked, deal stage transition within N days of the conversation. These are the true win-rate proxies; compute weekly in SQL.
- Published 2026 benchmarks for WhatsApp B2C admissions/sales agents (Uptail platform data — vendor data, single source, treat as calibration not gospel): response <5min 90-95% strong; **qualification rate 45-55% strong / <30% poor**; **call-booking rate of qualified 20-28% strong / <15% poor**; **human-handoff 15-25% strong / >35% poor**. Diagnostic pairing: high response + low qualification = conversation-design problem; high qualification + low booking = conversion friction. Source: https://www.uptail.ai/blog/admissions-ai-sales-agent-benchmarks-2026-what-response-rate-qualification-rate-and-call-booking-rate-should-you-expect
- `follow_up_within_minutes` (already logged) is the free per-turn dissatisfaction proxy.

**Per-turn judge layer (LLM-as-judge):**
- Judge dimensions for Gutty sales turns: (a) tone/persona match (Spanish, warm, Gutty voice), (b) **claim accuracy = groundedness vs the retrieved KB chunks / hardcoded FAQ strings in the prompt** (prices and plan details are the hallucination-critical surface), (c) next-step progression (did the reply move toward booking/qualification), (d) premature medical advice / missed handoff trigger.
- 2026 consensus architecture: "heuristics on every span, distilled judges on a sample, humans on the gold-set"; sample 5-20% uniform + 100% of flagged/error/low-confidence traces; cut sampling when judge cost >20-25% of production LLM cost. Sources: https://deepeval.com/guides/guides-llm-as-a-judge , https://futureagi.com/blog/llm-as-judge-best-practices-2026 , https://montecarlo.ai/blog-llm-as-judge/
- **Volume math flips the sampling advice for THIS business**: 500-2000 leads/mo × ~5 turns ≈ 2.5k-10k turns/mo, of which maybe 30-50% are LLM-composed (rest deterministic FAQ/dispatch). A Haiku-class judge call (~1-1.5k tokens in, ~150 out) costs well under a cent; judging **100% of LLM-composed turns costs on the order of $5-20/mo** — below the noise floor. Recommendation: judge 100% of LLM-composed turns nightly (async batch, not in the hot path), skip judging deterministic FAQ turns entirely (they can't drift), and route judge-failures into the existing review queue.

## 6. CRM-write correctness evals

- 2026 framing: tool-calling eval = 4 stacked problems — tool selection, argument extraction, result utilization, error recovery (https://futureagi.com/blog/evaluating-tool-calling-agents-2026/ , https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide). BFCL-style: AST/syntactic track + executable track (https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide).
- For Gutty v3 the right design is **deterministic, not judge-based**: CRM writes have exact expected values. Extend `eval/run_eval.py` with `--mode crm`: golden cases (conversation snippet → expected module/field/value writes), execute against **MockCrmAdapter or Zoho sandbox**, then **read-after-write via COQL** and assert field-level equality (module, record match by phone-suffix rule, field names, values, Note body contains required elements). LLM-judge only for free-text Note quality. This reuses the existing adapter split (`CRM_PROVIDER=mock`) and the existing `zoho_smoke_test.py` plumbing — small build, no vendor product required.
- In production, add a nightly **reconciliation check**: for every turn with `dispatch_tool` = a write tool and `task_outcome='replied'`, verify the corresponding Zoho record exists (catches silent write failures — the failure mode judges can't see).

## 7. Review-queue UX for ONE part-time quality owner

- Load estimate at 2000 leads/mo: after the plan's filters (clarify/fallback/low-conf/rapid-follow-up) plus judge-flagged turns, expect ~50-150 flagged turns/week → clustered into **~10-25 clusters/week** → **60-120 min/week** of review. This fits one part-time owner **only if clustering works and the queue is strictly prioritized**: (1) handoff/`task_outcome='error'`, (2) judge-flagged claim-accuracy failures, (3) CRM-write reconciliation failures, (4) misclassification clusters, (5) applied auto-reseeds to audit.
- The repo's **weekly clustered Markdown file is the right v1** — zero new UI, git-diffable, and the auto-apply-with-rollback design means the reviewer audits rather than gates (throughput doesn't bottleneck on them). Langfuse v3 **annotation queues** (MIT, self-hosted) or Phoenix annotations are the upgrade path when the reviewer wants click-through-to-trace UX instead of Markdown (https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues).
- Keep the plan's safety rails: rate-limited auto-apply (≤3 reseeds/day), eval-regression auto-revert at >2%, `revert_requested` undo. These are well-designed for a team this size; do not replace with approval gates (would bottleneck) or full autonomy (no rollback audit).

## 8. Frozen-weights learning loops (prompts/seeds, not weights)

- The repo's reseed loop (turn_log → cluster → seed append → re-seed → eval gate → auto-revert) **is** a frozen-weights learning loop and matches 2026 best practice for small teams: the "weights" are `intent_seeds.yaml` + the graph + prompt strings, all in git, all gated by the eval harness.
- **GEPA** (Genetic-Pareto reflective prompt evolution, DSPy) — ICLR 2026 oral; gradient-free, reflects on execution traces, evolves prompts; outperforms GRPO-style RL by up to ~20% with ~35× fewer rollouts. Production write-up: Decagon runs GEPA test-driven against golden sets. Sources: https://arxiv.org/pdf/2507.19457 , https://github.com/gepa-ai/gepa , https://dspy.ai/tutorials/gepa_ai_program/ , https://decagon.ai/blog/optimizing-gepa-for-production
- Verdict for Gutty: GEPA/DSPy is the **right eventual tool for the composition prompts** (Gutty persona/system prompts in `llm/composition.py`) but premature until there is a graded golden set of a few hundred sales conversations with outcome labels — the judge + turn_log pipeline built above **produces exactly that dataset as a by-product**. Revisit GEPA at ~300+ labeled cases; run it offline against the golden set, ship winners through the same eval-regression gate. Anthropic offers no Claude fine-tuning (repo doc, consistent with public state) — frozen-weights is not just prudent, it's the only option.

## 9. Options assessed

| # | Option | Verdict |
|---|---|---|
| 1 | Stay on Langfuse v2 (status quo) | Untenable beyond short term: server+SDK frozen, none of the MIT-ified eval features (judge, annotation queues) exist on v2; it's a trace viewer only. |
| 2 | Upgrade to Langfuse v3 self-hosted | Full MIT feature set incl. LLM-as-judge + annotation queues; well-funded post-acquisition. Cost: +ClickHouse(8GiB)+Redis+S3/MinIO containers and a v2→v3 data migration + SDK rewrite — heavy ops for 1-3 people on one droplet; needs droplet upgrade (~$48-96/mo DO tier). Viable, second choice. |
| 3 | Arize Phoenix self-hosted | Single container + existing Postgres, OTel-native collector built in, evals + annotations included, ELv2 fine for internal use. Requires re-instrumenting anthropic.py (small file) via OTel — which de-locks the stack anyway. Best ops-fit. |
| 4 | Cloud SaaS (LangSmith / Braintrust / Langfuse Cloud HIPAA region) | Rejected: PHI leaves the droplet; BAA tiers are paid (Langfuse HIPAA region = eligible plan + BAA; LangSmith = Enterprise); recurring cost buys nothing self-host doesn't give at this volume. |
| 5 | Postgres-only DIY (turn_log + eval harness + Markdown queue, no trace platform) | Surprisingly strong floor: turn_log already carries 80% of the review workflow. Keep it as the **system of record** regardless of platform; trace platform is a debugging lens, not the source of truth. |

## 10. Recommendation (for this business)

Keep **Postgres `turn_log` + `learning_queue` as the system of record** for evals and learning (already built, PHI-controlled, review workflow included). Re-instrument the LLM client **once, via OTel** (anthropic.py is 100 lines), and point it at **Phoenix single-container** on the existing droplet — or Langfuse v3 if the team prefers continuity and accepts the droplet upgrade + 3 extra containers; the OTel instrumentation makes this a config choice, not a rewrite. Then: (1) judge **100% of LLM-composed sales turns** nightly with a Haiku-class judge on tone/groundedness-vs-retrieved-context/next-step/missed-handoff (~$5-20/mo — ignore the 5-20% sampling folklore, it's for 100× this volume); (2) add `--mode crm` to the eval harness: deterministic COQL read-after-write assertions against Zoho sandbox, plus a nightly production write-reconciliation check; (3) compute win-rate proxies weekly in SQL from turn_log×Zoho joins (qualification-completeness, booking rate, stage transitions), calibrated against the Uptail-style benchmark bands; (4) keep the weekly clustered Markdown review at ≤2h/week with strict priority order, auto-apply + eval-regression rollback as designed; (5) defer GEPA/DSPy prompt optimization until the judge pipeline has produced ~300 labeled conversations, then run it offline through the same regression gate.

## Open questions

1. Langfuse v2 server has no published EOL — how long is the security-patch window really? (UNVERIFIED)
2. Does the droplet have headroom (RAM) for Phoenix+Postgres growth at 10k turns/mo, and who owns backup of trace data vs turn_log?
3. Are Venezuelan/LatAm patients under any local health-data law that changes the "self-host = compliant" assumption (HIPAA analog, habeas data)?
4. What fraction of v3 Master Operator turns will be LLM-composed vs deterministic? Judge cost and review load scale with that fraction.
5. Will the ONE quality owner accept a Markdown queue, or is annotation-queue UI (Langfuse v3) the adoption make-or-break? Worth a 2-week trial before infra commitment.
