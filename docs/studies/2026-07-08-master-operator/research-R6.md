# R6 — Knowledge + Tacit Extraction (Cerebro Gutty v3)

Researcher: R6. Date: 2026-07-08. Note: the orchestrator-supplied brief path and notes path were literally "undefined"; scope taken from the task message. Notes written to scratchpad (this file).

## 1. Current state (repo evidence)

- **Corpus is tiny and static**: 8 curated markdown files in `knowledge/raw/` (company overview, plans, exams catalog, supplements, specialists, FAQ, contacts, voice). README says "only approved content" — an implicit human approval gate already exists. (`knowledge/raw/README.md`)
- **Ingest is one-shot, no change detection**: `src/company_agent/ingest_worker/main.py` walks the folder, upserts document rows on `source_uri`, then **deletes and re-inserts + re-embeds every chunk of every document on every sync**, whether or not content changed. No content hash, no mtime check. Fine at 8 docs; wasteful and slow at Drive scale.
- **Chunking is naive char-based** (`common/text.py`: 1200 chars, 180 overlap, paragraph packing). No heading path, no doc-level context prepended → classic "context-loss" chunks.
- **Lexical FTS uses `'simple'` tsconfig** in both the generated column (`sql/001_init.sql:26-28`) and the query (`rag_api/search.py:21-23`). `'simple'` does **no Spanish stemming and is accent-sensitive**: "consulta" won't match "consultas"; "nutricion" (typed without accent, very common on WhatsApp) won't match "nutrición". This measurably cripples the lexical leg of the RRF hybrid for a Spanish-only corpus.
- **No reranker**; fusion is RRF (rrf_k=60) over lexical + pgvector cosine (OpenAI 1536-dim).
- **Deterministic price boundary exists but is duplicated ~7 places**: plan prices $229/$559/$789 are hardcoded in `openclaw/plugins/customer-service-tools/index.js`, `src/company_agent/agent_core/tasks/customer_service.py` (DIRECT_FAQ_REPLIES), `knowledge/raw/02_consultation_plans.md`, `knowledge/raw/06_faq.md`, `eval/seeds.yaml`, `eval/system_prompt.md`, plus archived policy docs. Grep-verified. A price change today requires 5+ coordinated edits across two runtimes, the KB, and the eval suite — high drift risk.
- **Price leakage into the retrieval path is possible today**: prices live in `knowledge/raw/02` and `06`, which are retrievable via `kb_search`; the LLM fallback path (`customer_service.py` step 6) composes freely, so a paraphrased/hallucination-adjacent price answer is reachable when intent classification misses `faq_consultation_plans`.
- Brain plan (`docs/nutriwhite-brain-plan.md`) already envisions a `learning_queue` + "self-learning ingestion gate" (§11.5) and seeds a domain graph from `knowledge/raw/` — R6 pipeline outputs should land as markdown in the same folder convention so ingest-worker and graph seeding both benefit.

## 2. Google Drive → RAG continuous ingestion

- **Change detection**: Drive API v3 `changes.list` with a persisted `pageToken` gives reliable incremental sync ("Changes and revisions overview", https://developers.google.com/workspace/drive/api/guides/change-overview; https://developers.google.com/workspace/drive/api/guides/manage-changes). For a 1–3 person team, **cron polling every 5–15 min beats push notifications** — `watch` channels expire and need renewal plumbing plus a public HTTPS endpoint; polling is a 50-line addition to ingest-worker.
- **Quota caution (2026)**: Drive API usage limits changed for Cloud projects created on/after 2026-05-01, and Google plans to **bill quota overages later in 2026** (https://developers.google.com/workspace/drive/api/release-notes, https://developers.google.com/workspace/drive/api/guides/limits). Polling a single folder is far below limits, but budget assumptions should not assume "free forever". UNVERIFIED: exact overage pricing (not yet published in fetched results).
- **Format**: Google Docs export directly to Markdown via `files.export` mimeType `text/markdown` (GA since July 2024, https://workspaceupdates.googleblog.com/2024/07/import-and-export-markdown-in-google-docs.html) — output plugs straight into the existing `chunk_markdown` path with zero new parsing code.
- **Permissions model**: do NOT mirror per-file Drive ACLs into the RAG store. Instead: one service account with read access to a single curated **"Gutty Knowledge" shared folder**; folder membership = the ingestion allowlist = the approval gate. Anything in the folder is by definition public-to-patients content. This matches the README's "only approved content" rule and avoids the entire ACL-sync problem class. Staff edit Google Docs (no git skills needed) — this is the operational win for this team.
- **Deletion handling**: `changes.list` reports removals; ingest must delete `knowledge_documents` by `source_uri` (Drive fileId) — the current pipeline has no delete path for vanished sources (repo gap).
- **Verdict**: build it in-house (Drive source adapter in ingest-worker + content-hash skip + tombstone deletes). Managed connectors (Ragie, Vectorize, LlamaCloud, Unstructured) add a vendor, move company data out of the stack, and duplicate a working pgvector pipeline — not justified at this corpus size.

## 3. Website / Academy scraping + freshness

- Sites: nutriwhitesalud.com (ES), nutriwhite.us (EN), patient portal, Academy (paid courses), blog (`knowledge/raw/07_contact_channels.md`).
- Scale is dozens-to-low-hundreds of pages → a **cron scraper keyed on sitemap `lastmod` + content hash**, writing markdown into the Drive folder / knowledge dir, is sufficient. Firecrawl (Hobby $16/mo, 1 credit/page, change-tracking + `maxAge` caching; credits expire monthly; 5x credits behind bot protection — https://www.firecrawl.dev/pricing) is a reasonable buy **only if** the sites are JS-heavy or bot-protected; otherwise unnecessary spend.
- **Academy caution (business, not technical)**: paid course content ingested into the free WhatsApp agent = giving the product away. Ingest **catalog, titles, descriptions, prices-as-deterministic-facts only**, never full course bodies.

## 4. Tacit knowledge extraction (founder/staff → SOP → chunks)

Two proven, complementary sources:

1. **Structured interviews**: Critical Decision Method (CDM) and the lighter Applied Cognitive Task Analysis (ACTA) are the best-evidenced elicitation techniques (systematic review in health services: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8903544/; practitioner method: https://commoncog.com/an-easier-method-for-extracting-tacit-knowledge/). Practical loop for this team: monthly 45–60 min recorded Spanish interview with founder/asesora anchored on **specific recent hard cases** ("cuéntame la última vez que un paciente…"), Whisper transcription, LLM drafts an SOP markdown (decision points, exceptions, exact recommended phrasings), **owner signs off**, doc lands in the Gutty Knowledge folder → existing ingest. Cost ≈ 1 staff-hour + cents of LLM.
2. **Conversation mining (higher yield, PHI-gated)**: the asesoras' real WhatsApp answers are the densest tacit corpus. `turn_log` + handoff transcripts capture them, and the planned `learning_queue` (brain plan §11.5) is exactly the right human-review gate. Hard rule: mined candidate knowledge must be **de-identified before it becomes a chunk** (chunks are retrievable by any patient session — cross-patient PHI leakage is the failure mode). Extract the *pattern/answer*, never the patient story.
- NLP-only "automatic tacit extraction" pipelines exist in the literature (https://www.mdpi.com/2227-7080/13/2/87) but human review remains mandatory for clinical-adjacent content; treat vendor claims of fully automatic SOP generation skeptically.

## 5. Retrieval quality: contextual retrieval, reranker, Spanish tsconfig

- **Spanish tsconfig (cheapest, highest-certainty fix)**: create a custom config = Spanish snowball stemmer + `unaccent` dictionary; use it in both the generated `search_tsv` column and `websearch_to_tsquery`. Gotcha: the `unaccent()` *function* is STABLE, not IMMUTABLE, so it can't sit directly in a `GENERATED ALWAYS` expression — the standard fix is putting the unaccent *dictionary inside the text search configuration* (docs: https://www.postgresql.org/docs/current/unaccent.html, https://www.postgresql.org/docs/current/textsearch-dictionaries.html). Requires a schema change (bootstrapped SQL, so a manual prod migration via `scripts/apply_brain_sql.sh` conventions) + full re-ingest. Cost ~0.
- **Contextual retrieval (Anthropic, Sep 2024)**: prepend an LLM-written 50–100-token doc-context blurb to each chunk before embedding + FTS. With prompt caching, indexing ≈ **$1.02 per million document tokens** (https://www.anthropic.com/engineering/contextual-retrieval); NutriWhite's corpus is well under 1M tokens → ~$1 per full re-index, trivially affordable even with the current re-embed-everything sync. Anthropic reports up to 49% retrieval-failure reduction (67% with reranking) — vendor-reported numbers on their benchmarks, but the technique is widely replicated (Milvus, Together, DataCamp implementations). Slot it into ingest-worker between `chunk_markdown` and embed.
- **Rerankers**: Cohere Rerank 3.5 — $2.00/1k searches, 100+ languages, strong Spanish (https://cohere.com/pricing, https://openrouter.ai/cohere/rerank-v3.5). Voyage rerank-2.5 — $0.05/M tokens, first 200M tokens free (https://docs.voyageai.com/docs/pricing) → effectively free at this volume. At ~5–20k kb_search calls/mo either is <$40/mo. **PHI touchpoint**: the rerank query is the patient's utterance (often health info) — requires DPA/zero-retention/BAA verification before adoption (UNVERIFIED for both vendors' current terms). Verdict: **defer** — fix tsconfig + contextual retrieval first, add a reranker only if an eval set (extend `eval/` with retrieval cases) still shows misses; a self-hosted bge-reranker-v2-m3 on the droplet is the PHI-clean fallback.
- Embedding model: keep OpenAI 1536-dim (schema-locked `VECTOR(1536)`, HNSW index); switching models forces a full re-embed + possibly a column change — not worth it now.

## 6. Deterministic vs retrieved boundary for prices/policies

Principle confirmed by repo design and should be hardened, not relaxed:

1. **Single source of truth**: a `facts/prices.yaml` (plan prices, installment policy, exam SKU prices, payment methods) that **renders** at build/deploy time into: the DIRECT_FAQ_REPLIES strings (both runtimes), the `knowledge/raw/*.md` price mentions, and `eval/seeds.yaml` assertions. Kills the 7-location drift.
2. **Prices must never be retrieved-then-paraphrased**: (a) tag price-bearing chunks `metadata.contains_price=true` and have the LLM-composition path either exclude them or render price lines **verbatim only**; (b) add a composition guard to FALLBACK_SYSTEM: "nunca menciones un precio que no venga del bloque de hechos"; (c) add an output check (regex for `$\d`) that blocks/flags any LLM-composed reply containing a price not present in the deterministic fact table — cheap and deterministic.
3. Same treatment for hard policies (installments TDC-only +3%, no direct insurance).

## 7. Knowledge-freshness gates

- Add `verified_at` + `valid_until` (optional) + `owner` to document/chunk metadata at ingest; retrieval demotes (RRF score penalty) or annotates chunks past TTL by content class — suggested: policies 90d, general/clinical-educational 365d, prices exempt (deterministic path).
- Weekly cron: stale-content report to the team WhatsApp group (reuses the existing team-group plumbing) listing docs past `verified_at` TTL; a human re-blesses by touching the Doc (Drive `modifiedTime` bump → re-ingest → fresh `verified_at`).
- Publish gate stays human: nothing enters the Gutty Knowledge folder without owner approval; mined/interview-derived docs additionally pass the `learning_queue` review (Phase 4 design already anticipates this).

## 8. Options summary

| Option | Verdict |
|---|---|
| A. Status quo: git-managed knowledge/raw + manual ingest | Keep short-term; ceiling ~50 docs and blocks non-technical staff |
| B. Drive shared-folder → changes.list polling adapter in ingest-worker (md export, content-hash skip, tombstones) | **Adopt** — the Fase 1–2 pipeline |
| C. Managed ingestion SaaS (Ragie/Vectorize/LlamaCloud/Unstructured) | Reject — vendor + data egress + duplicates working pipeline |
| D. Spanish tsconfig (+unaccent) + contextual retrieval | **Adopt** — cheapest highest-certainty retrieval gains |
| E. External reranker (Cohere 3.5 / Voyage 2.5) | Defer pending retrieval eval + PHI/DPA check; self-host fallback |
| F. Firecrawl for site/Academy | Conditional — cron+sitemap-hash scraper first; $16/mo Firecrawl only if bot-protection/JS blocks |
| G. Tacit program: monthly CDM/ACTA interviews → LLM-drafted SOP → owner sign-off; + de-identified turn_log mining via learning_queue | **Adopt** |

## 9. Open questions

1. Cohere/Voyage current DPA / zero-data-retention / BAA terms for rerank queries containing patient utterances (PHI) — UNVERIFIED, must check before any external reranker.
2. May Academy paid-course content be surfaced (even summarized) to free WhatsApp users? Business decision, blocks Academy ingestion depth.
3. Target corpus size in 12 months (determines when re-embed-all sync must become hash-incremental — recommend building hash-skip from day one anyway).
4. Google Drive API quota-overage pricing "later in 2026" — announced but pricing not published in fetched sources.
5. Who is the single named owner of `facts/prices.yaml` (price changes are currently diffused across 3 people/7 files)?
