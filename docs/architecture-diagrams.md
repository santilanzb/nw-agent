# NutriWhite Agent — Architecture Diagrams

Visual reference for the Gutty WhatsApp agent stack. Renders inline in GitHub. Each diagram is followed by a "what this reveals" commentary so you can spot weak spots and future upgrades.

Last reviewed: 2026-05-14, after Phase 1 (intent router) shipped and Phase 2 (deterministic inbound_claim hook) planned.

---

## 1. System overview — services and where they run

```mermaid
graph TB
    subgraph Internet
        Patient[("Patient<br/>WhatsApp")]
        Team[("Logistics Team<br/>WhatsApp Group<br/>'Gutty Agent'")]
        Meta[(WhatsApp Web<br/>servers)]
    end

    subgraph Droplet["Ubuntu Droplet · 165.227.73.90"]
        subgraph Host["Host · systemd --user"]
            OC["OpenClaw Gateway<br/>:18789 loopback<br/>v2026.5.7"]
            WAP["@openclaw/whatsapp<br/>plugin"]
            Plug["customer-service-tools<br/>plugin"]
            Hook{{"inbound_claim hook<br/>· Phase 2 ·"}}
            Skills["Workspace<br/>/.openclaw/workspace/AGENTS.md<br/>/.openclaw/skills/.../SKILL.md"]
            OC --> WAP
            OC --> Plug
            Plug --> Hook
            OC --> Skills
        end

        subgraph DockerCompose["Docker Compose"]
            RAG["rag-api · :8081<br/>FastAPI<br/>· hybrid retrieval<br/>· classify_intent"]
            CRM["crm-adapter · :8082<br/>FastAPI<br/>· handoff state<br/>· Zoho reads/writes"]
            PG[("Postgres + pgvector<br/>:5432<br/>· knowledge_chunks<br/>· intent_vectors<br/>· handoff_state")]
            Ingest["ingest-worker<br/>(oneshot)"]
            Seeder["intent_seeder<br/>(oneshot)"]
        end
    end

    subgraph External
        OAI["OpenAI<br/>text-embedding-3-small"]
        Anth["Anthropic API<br/>claude-sonnet-4-6"]
        Zoho[("Zoho CRM v8<br/>COQL + REST")]
    end

    Patient <-->|messages| Meta
    Team <-->|messages| Meta
    Meta <-->|WhatsApp Web protocol| WAP

    Hook <-->|HTTP loopback| RAG
    Hook <-->|HTTP loopback| CRM
    Plug <-.->|LLM path| Anth
    Plug <-->|HTTP loopback| RAG
    Plug <-->|HTTP loopback| CRM

    RAG <-->|psycopg| PG
    RAG -->|embed query| OAI
    CRM <-->|psycopg| PG
    CRM <-->|OAuth + COQL| Zoho
    Ingest -->|UPSERT chunks| PG
    Ingest -->|embed docs| OAI
    Seeder -->|UPSERT vectors| PG
    Seeder -->|embed phrases| OAI

    classDef external fill:#fff3e0,stroke:#e65100
    classDef internal fill:#e3f2fd,stroke:#1565c0
    classDef storage fill:#f3e5f5,stroke:#6a1b9a
    classDef hook fill:#e8f5e9,stroke:#2e7d32,stroke-width:3px
    class OAI,Anth,Zoho,Patient,Team,Meta external
    class OC,WAP,Plug,RAG,CRM,Skills,Ingest,Seeder internal
    class PG storage
    class Hook hook
```

### What this reveals

- **Three trust zones.** Internet → Droplet (only WhatsApp Web traffic) → Loopback (all internal HTTP on 127.0.0.1). No service is publicly exposed except OpenClaw's WhatsApp listener.
- **Single droplet, single failure domain.** Postgres, the agent, and the gateway all live on the same box. Disk loss = everything. **Upgrade target:** managed Postgres on DigitalOcean before any real patient traffic.
- **Two external dependencies on the hot path:** Anthropic (only when LLM fallback path triggers) and OpenAI (every classify call). OpenAI outage = classifier fails → hook falls open to LLM → potentially worse behavior. **Upgrade target:** cache the embedding for repeat queries (5-10 min TTL) to absorb brief outages.
- **Zoho is on the hot path for handoffs** but reads are COQL (slow). **Upgrade target:** lazy-write Notes async so the patient-facing handoff reply isn't blocked on Zoho latency.

---

## 2. Inbound message decision tree — the critical flow

```mermaid
flowchart TD
    Start([Patient sends message]) --> WA[WhatsApp plugin receives]
    WA --> Hook[inbound_claim hook fires]

    Hook --> IsGroup{Group?}
    IsGroup -->|yes| ToLLMa["handled: false<br/>LLM handles team commands"]

    IsGroup -->|no| HasPhone{senderId?}
    HasPhone -->|no| ToLLMb["handled: false<br/>fail open"]

    HasPhone -->|yes| StateCheck[/POST /v1/handoff/state/check/]
    StateCheck -->|HTTP error| ToLLMc["handled: false<br/>fail open"]
    StateCheck --> Active{active = true?}
    Active -->|yes| Silent["handled: true<br/>NO REPLY · SILENT MUTE"]:::silent

    Active -->|no| Classify[/POST /v1/classify_intent/]
    Classify -->|HTTP error| ToLLMd["handled: false<br/>fail open"]
    Classify --> Decision{decision}

    Decision -->|clarify| ToLLMe["handled: false<br/>LLM asks 1 clarifying question"]
    Decision -->|fallback_llm| ToLLMf["handled: false<br/>LLM uses full policy"]

    Decision -->|execute| Dispatch{dispatch.tool}

    Dispatch -->|handoff_human| Handoff[/POST /v1/handoff/]:::deterministic
    Handoff --> HandoffOK{success?}
    HandoffOK -->|yes| SendHandoff["handled: true<br/>send handoff phrase"]:::deterministic
    HandoffOK -->|err once| Retry[retry 250ms]
    Retry -->|still err| LogLoud["log ERROR + send phrase<br/>missed-reply watchdog catches"]:::warn
    Retry -->|ok| SendHandoff

    Dispatch -->|faq_location<br/>faq_services<br/>faq_consultation_plans<br/>faq_payment_methods| SendFAQ["handled: true<br/>send canned text"]:::deterministic

    Dispatch -->|null + acknowledgment| AckSilent["handled: true<br/>NO REPLY"]:::silent

    Dispatch -->|null + greeting/farewell| ToLLMg["handled: false<br/>LLM responds in tone"]

    Dispatch -->|customer_lookup<br/>patient_plan_status<br/>patient_appointment_status<br/>patient_exam_status| ToLLMh["handled: false<br/>LLM composes from CRM"]

    Dispatch -->|kb_search<br/>faq_consultation_call<br/>faq_protocol_3r<br/>faq_supplements_general<br/>faq_exams_general| ToLLMi["handled: false<br/>LLM composes from KB"]

    ToLLMa & ToLLMb & ToLLMc & ToLLMd & ToLLMe & ToLLMf & ToLLMg & ToLLMh & ToLLMi --> LLM[Sonnet 4.6 composes]
    LLM --> Reply

    Silent & SendHandoff & SendFAQ & AckSilent & LogLoud --> Reply([Patient sees reply or silence])

    classDef silent fill:#fce4ec,stroke:#c2185b
    classDef deterministic fill:#e8f5e9,stroke:#2e7d32
    classDef warn fill:#fff3e0,stroke:#e65100
```

### What this reveals

- **Three deterministic exits, six LLM exits.** Roughly: handoffs + canned FAQs + active mute + acknowledgment skip the LLM. Greetings, KB-backed FAQs, patient-specific lookups, and ambiguous routing still need it.
- **Fail-open everywhere.** Every HTTP error from the hook falls through to the LLM. Good for availability. Bad for cost spikes if RAG or CRM is sick. **Upgrade target:** circuit breaker — if classify_intent has failed N times in M seconds, return a static "tengo un problema técnico, te conecto con asesora" instead of LLM fallback.
- **The retry on /v1/handoff is the only retry in the system.** Every other HTTP call is single-shot. **Upgrade target:** small retry budget on the classify call too — current "fail open" is too aggressive for transient errors.
- **No rate limiting at the hook layer.** A patient spamming 100 messages incurs 100 classify calls and 100 potential LLM calls. **Upgrade target:** per-phone token bucket (e.g. 5 messages / 60s) at the hook entry.

---

## 3. Handoff lifecycle — state machine

```mermaid
stateDiagram-v2
    direction LR
    [*] --> pending: POST /v1/handoff<br/>(hook or LLM)

    pending --> claimed: "@Gutty tomo +58..."<br/>(team group)
    pending --> resumed: New handoff for same phone<br/>(supersession)
    pending --> resumed: "@Gutty resume +58..."<br/>(rare — preempt)
    pending --> expired: 24h elapsed<br/>(lazy on next state check)

    claimed --> resumed: "@Gutty resume +58..."<br/>(team marks done)
    claimed --> expired: 24h elapsed

    resumed --> [*]: Gutty answers patient again
    expired --> [*]: Gutty answers patient again

    note right of pending
        check_handoff_state → active=true
        Hook returns handled:true (no reply)
        Patient gets silence
    end note

    note right of claimed
        check_handoff_state → active=true
        Patient still gets silence
        Human handles directly via her WhatsApp
        claimed_by_phone/name populated
    end note

    note left of expired
        Status flipped lazily on next read
        via HandoffStateStore._expire_old()
    end note
```

### What this reveals

- **Two ways to leave the active state:** explicit resume or 24h timeout. The 24h fallback is the safety net so a forgotten claim doesn't permanently mute a patient.
- **No "escalated" path.** If the team can't reach a patient and wants to mark the case unresolved, current options are limited — claim then leave it to expire, or resume manually. **Upgrade target:** add a `failed` terminal state plus a `team_close_handoff` tool with optional reason.
- **No claim history.** Resuming clears `claimed_by_*` fields on the next pending row, but we can see past handoffs by querying `WHERE status='resumed'`. **Upgrade target:** keep a small audit table per claim if reporting needs it; otherwise the current single-row-per-handoff design is fine for v1.
- **Supersession is silent.** A new handoff for the same phone resumes the prior one without notifying the original claimer. **Upgrade target:** if a claimed handoff is superseded, ping the claimer in the team group so they know the case state changed.

---

## 4. Team group command flow — claim and resume

```mermaid
sequenceDiagram
    autonumber
    participant P as Patient<br/>+584145610594
    participant G as Gutty<br/>(+584123251172)
    participant H as inbound_claim<br/>hook
    participant CRM as crm-adapter
    participant L as Sonnet 4.6<br/>(LLM)
    participant TG as "Gutty Agent"<br/>group
    participant M as María<br/>(operator)

    P->>G: "Necesito un especialista, tengo gastritis crónica"
    G->>H: inbound_claim event
    H->>CRM: classify_intent → handoff_specialist_recommendation (0.98, execute)
    H->>CRM: POST /v1/handoff (contact_phone=+584145610594)
    Note over CRM: INSERT handoff_state<br/>status=pending
    H-->>G: handled:true · reply=handoff phrase
    G-->>P: "Para esto te conecto con una asesora 🩵"

    Note over TG: ⚠ Phase 2 gap: hook does NOT push<br/>structured notification to TG yet.<br/>Team learns via Zoho Note alert.

    M->>TG: "@Gutty tomo +584145610594"
    TG->>G: inbound (group, mention)
    G->>H: inbound_claim event
    Note over H: isGroup=true → handled:false
    G->>L: agent processes group msg
    L->>CRM: team_claim_handoff
    Note over CRM: UPDATE status=claimed<br/>claimed_by=María
    L-->>TG: "✅ Listo, María. Tomas el caso..."

    P->>G: "ok cuándo me responden?"
    G->>H: inbound_claim event
    H->>CRM: state check → active=true (claimed)
    Note over H: handled:true (silent)
    G--xP: (no reply)

    M->>P: (DM from María's own WhatsApp)<br/>handles full case

    M->>TG: "@Gutty resume +584145610594"
    TG->>G: inbound (group, mention)
    G->>L: agent processes
    L->>CRM: team_resume_handoff
    Note over CRM: UPDATE status=resumed<br/>resumed_at=NOW()
    L-->>TG: "✅ Caso cerrado. Vuelvo a atender."

    P->>G: "Hola buenos días"
    G->>H: inbound_claim event
    H->>CRM: state check → active=false
    H->>CRM: classify_intent → greeting (0.92, execute, tool=null)
    Note over H: handled:false → LLM
    G->>L: respond
    L-->>P: "¡Hola buenos días! 🩵 ¿En qué te puedo ayudar?"
```

### What this reveals

- **The TEAM side still depends on the LLM.** Step 7–10 (María's `@Gutty tomo` command) goes through the agent loop. Same reliability problem we just solved for patients. **Upgrade target:** detect team-group commands in the hook (`isGroup && content.startsWith('@Gutty tomo|resume')`) and call the team-claim/resume endpoint directly without invoking the LLM at all.
- **No active notification of the team on handoff.** Step 4-6 fires but the operators only learn through a Zoho Note (which requires watching the CRM) or out-of-band channels. **Upgrade target:** the hook should POST to OpenClaw's outbound send API to push a structured message into the team group on every handoff. Blocked on discovering the send-to-JID method — the build agent flagged this as Phase 2 follow-up.
- **The team must @-mention Gutty.** If María just writes "tomo el caso" without `@Gutty`, OpenClaw's `requireMention: true` policy drops it. **Possible upgrade:** auto-treat any team-group message from one of the known operator phone numbers as targeted, regardless of mention.

---

## 5. Data model — what lives where

```mermaid
erDiagram
    knowledge_documents ||--o{ knowledge_chunks : "chunks of"
    knowledge_documents {
        uuid id PK
        text source_uri UK "knowledge/raw/02_consultation_plans.md"
        text source_type "md, txt, json"
        text title
        text content_md
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }

    knowledge_chunks {
        uuid id PK
        uuid document_id FK
        text corpus "default"
        int chunk_index
        text title
        text content "1200 chars max"
        text source_uri
        jsonb metadata
        vector embedding "1536-dim · pgvector"
        tsvector search_tsv "FTS · generated"
    }

    intent_vectors {
        uuid id PK
        text intent_class "handoff_specialist_recommendation"
        text example_text "qué especialista para gastritis"
        text language "es | en"
        vector embedding "1536-dim · pgvector"
        jsonb metadata "{dispatch: {...}}"
        timestamptz created_at
    }

    handoff_state {
        uuid id PK
        text contact_phone "+584145610594"
        text contact_id "Zoho Contact id"
        text patient_name
        text conversation_id "OpenClaw session key"
        text status "pending|claimed|resumed|expired"
        text reason
        text priority "high|normal|urgent|low"
        text last_message
        text zoho_note_id
        text claimed_by_phone
        text claimed_by_name
        timestamptz created_at
        timestamptz claimed_at
        timestamptz resumed_at
        timestamptz expires_at "+24h default"
    }
```

Plus what does NOT live in Postgres:

| Data | Lives in | Why |
|---|---|---|
| Customer profile (Contacts) | Zoho CRM | System of record for patient identity |
| Deals / plans (Tratos) | Zoho CRM | Sales pipeline lives there |
| Consultas | Zoho custom module | Operational calendar |
| Exámenes | Zoho custom module | Lab results live there |
| Handoff Notes | Zoho Contacts.Notes | Audit trail / human-readable history |
| Message journal | JSONL on disk `/root/nw-agent/runtime/openclaw-message-journal.jsonl` | Watchdog for missed replies |
| OpenClaw session state | `~/.openclaw/agents/nw-cs-agent/sessions/sessions.json` | Per-conversation continuity |
| OpenClaw config | `~/.openclaw/openclaw.json` | Channel auth, model, plugin config |

### What this reveals

- **Zero PII in Postgres beyond phone number + name.** Everything sensitive (full patient record, financial data, exam results) lives in Zoho. Postgres is operational state.
- **No retention policy on handoff_state.** Rows accumulate forever (currently a handful, but at scale will need it). **Upgrade target:** add a `cleanup` cron that hard-deletes `status IN ('resumed', 'expired')` rows older than 90 days.
- **No index on `handoff_state.contact_id`.** Lookups by Zoho contact ID would do a seq scan. Not currently used but worth adding before any tool calls this path.
- **The message journal is on the host filesystem.** Disk crash = lost watchdog history. Acceptable for now; **upgrade target:** ship to S3/Spaces.

---

## 6. Tool registration map — what the agent can call

| Tool | Backend | Called by hook | Called by LLM | Determinism |
|---|---|:-:|:-:|---|
| `check_handoff_state` | crm-adapter `/v1/handoff/state/check` | ✓ first | (redundant) | 100% |
| `classify_intent` | rag-api `/v1/classify_intent` | ✓ second | (redundant) | 100% |
| `handoff_human` | crm-adapter `/v1/handoff` | ✓ on execute+specialist/etc. | only if hook falls open | 100% on hook path |
| `faq_location` | inline canned (DIRECT_FAQ_REPLIES) | ✓ on execute | rare | 100% on hook path |
| `faq_services` | inline canned | ✓ on execute | rare | 100% on hook path |
| `faq_consultation_plans` | inline canned | ✓ on execute | rare | 100% on hook path |
| `faq_payment_methods` | inline canned | ✓ on execute | rare | 100% on hook path |
| `faq_consultation_call` | kb_search via classify dispatch | LLM only | ✓ | LLM-dependent |
| `faq_protocol_3r` | kb_search | LLM only | ✓ | LLM-dependent |
| `faq_supplements_general` | kb_search | LLM only | ✓ | LLM-dependent |
| `faq_exams_general` | kb_search | LLM only | ✓ | LLM-dependent |
| `kb_search` | rag-api `/v1/retrieve` | — | ✓ | LLM-dependent |
| `customer_lookup` | crm-adapter `/v1/customer/profile` | — | ✓ | LLM-dependent |
| `customer_orders` | crm-adapter `/v1/customer/orders` | — | ✓ | LLM-dependent |
| `customer_consultas` | crm-adapter `/v1/customer/tickets` | — | ✓ | LLM-dependent |
| `customer_examenes` | crm-adapter `/v1/customer/examenes` | — | ✓ | LLM-dependent |
| `team_claim_handoff` | crm-adapter `/v1/handoff/claim` | — | ✓ | LLM-dependent |
| `team_resume_handoff` | crm-adapter `/v1/handoff/resume` | — | ✓ | LLM-dependent |
| `ticket_create_draft` | crm-adapter `/v1/tickets/draft` | — | ✓ | LLM-dependent |

### What this reveals

- **Roughly 50/50 split** between deterministic (hook) and probabilistic (LLM) paths. The LLM still owns a lot of the surface area.
- **Team commands are LLM-dependent.** Same reliability risk as patient handoff was, pre-hook. Worth moving to the hook in a follow-up.
- **Patient-specific lookups (`customer_*`) are all LLM-dependent.** Acceptable because they require composition — the LLM is genuinely useful for "respond about your plan in Gutty's voice." Determinizing these would require templating per-intent.

---

## 7. Where reliability fails today — known gaps

```mermaid
graph LR
    subgraph "🟢 Now bulletproof"
        A1[Active-handoff mute]
        A2[handoff_specialist_recommendation dispatch]
        A3[faq_location/services/plans/payment]
        A4[Acknowledgment silence]
    end

    subgraph "🟡 Reliable but LLM-dependent"
        B1[greeting / farewell]
        B2[kb_search-backed FAQs<br/>3R, supplements, exams catalog]
        B3[customer_lookup-backed patient_* intents]
        B4[clarify path]
    end

    subgraph "🟠 Still risky"
        C1[Team-group commands<br/>@Gutty tomo / resume]
        C2[fallback_llm path<br/>truly novel messages]
        C3[Zoho Note write reliability<br/>on handoff_human]
    end

    subgraph "🔴 Not yet built"
        D1[Active push to team group<br/>on handoff fire]
        D2[Rate limiting per phone]
        D3[Circuit breaker on classify_intent]
        D4[handoff_state cleanup / retention]
    end

    classDef green fill:#e8f5e9,stroke:#2e7d32
    classDef yellow fill:#fffde7,stroke:#f9a825
    classDef orange fill:#ffe0b2,stroke:#e65100
    classDef red fill:#ffebee,stroke:#c62828

    class A1,A2,A3,A4 green
    class B1,B2,B3,B4 yellow
    class C1,C2,C3 orange
    class D1,D2,D3,D4 red
```

### Triage

**Immediate (next sprint, after Phase 2 ships):**
- 🟠 C1 — extend the hook to handle team-group commands deterministically too.
- 🔴 D1 — discover OpenClaw's send-to-JID API; if found, push handoff notifications to the team group from the hook.

**Soon (next month):**
- 🔴 D4 — add a small daily cleanup job for `handoff_state` rows older than 90 days.
- 🟠 C3 — make Zoho Note creation async / fire-and-forget so it doesn't block the patient reply.

**Operational hardening (before scale):**
- 🔴 D2 + D3 — per-phone rate limit and circuit breaker.
- Move Postgres off the droplet (managed instance).
- Move WhatsApp allowlist from single tester (`+584241329676`) to production rollout with team + early-access patients.

---

## 8. Phase summary — where we've been, where we're going

```mermaid
gantt
    title NutriWhite Agent Build Timeline
    dateFormat YYYY-MM-DD
    section Foundation
    Repo scaffold, rag-api, crm-adapter (mock)    :done,    f1, 2026-04-24, 5d
    Zoho adapter, COQL, Notes write               :done,    f2, after f1, 3d
    Liliana persona, FAQ tools, eval harness      :done,    f3, after f2, 3d

    section Phase 1
    Rename Liliana → Gutty                        :done,    p1a, 2026-05-12, 1d
    Handoff state table + claim/resume            :done,    p1b, after p1a, 1d
    Intent router (20 classes, 99.1% eval)        :done,    p1c, after p1b, 2d

    section Phase 2 (in flight)
    Seed coverage fix (specialist 0.74 → 0.98)    :done,    p2a, 2026-05-14, 1d
    inbound_claim hook spec                       :done,    p2b, after p2a, 1d
    inbound_claim hook implementation             :active,  p2c, 2026-05-14, 2d
    Smoke tests + production cutover              :         p2d, after p2c, 1d

    section Phase 3 (planned)
    Team-group hook (deterministic claim/resume)  :         p3a, 2026-05-18, 3d
    Active team push on handoff fire              :         p3b, after p3a, 2d
    Rate limit + circuit breaker                  :         p3c, after p3b, 2d
    Retention / cleanup jobs                      :         p3d, after p3c, 1d

    section Phase 4 (production)
    Managed Postgres migration                    :         p4a, 2026-06-01, 2d
    Expand allowlist → real patient rollout       :         p4b, after p4a, 1d
    Observability (Langfuse / metrics)            :         p4c, after p4b, 3d
```

---

## How to read this doc

- **Diagrams 1-2** describe the architecture as planned post-Phase-2 — what you'll see after the inbound_claim hook ships.
- **Diagrams 3-5** describe state and data flow that's already in place today.
- **Diagrams 6-7** are the honest scorecard. What's solid, what's still LLM-dependent, what's a known gap.
- **Diagram 8** is the rough timeline so you can see what we've burnt and what's left.

Use this doc when:
- A new collaborator needs to understand the system without reading the whole repo.
- You're deciding whether to take on an upgrade — find it in §7 to see priority.
- Something breaks in production — §2 is the decision tree to walk through.
- You want to spot architectural smells — read the "What this reveals" blocks under each diagram.
