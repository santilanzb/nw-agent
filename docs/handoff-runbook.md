# Handoff and ticket — operator runbook

What the team sees, what it means, and what to do when it goes wrong. The design
rules behind all of this are in `CLAUDE.md` under *Handoff and ticket — the Phase
3 rules*; this is the operational half.

---

## The lifecycle

```
pending  →  a handoff fired; the team group has been told
claimed  →  an asesora typed "@Gutty tomo +58…"; Gutty is silent for that patient
resumed  →  she typed "@Gutty resume +58…"; Gutty answers again
expired  →  the window ran out; Gutty answers again and the group is told
```

Two windows, because a case nobody picks up and a case someone picked up are
different failures:

| | env var | default | measured from |
|---|---|---|---|
| unclaimed | `HANDOFF_PENDING_EXPIRE_HOURS` | 4 h | the handoff firing |
| claimed | `HANDOFF_CLAIMED_EXPIRE_HOURS` | 24 h | **the claim**, not the creation |

The claimed clock restarting at the claim is deliberate: with one 24 h clock from
creation, a case taken at hour 23 expired an hour later, mid-conversation.

A patient stops being muted the moment their window ends, not when the sweep gets
to it. The sweep exists to *close and announce*, not to unmute.

---

## What the group sees

**A new case.** `Ticket:` is the first 8 characters of the ticket id — the
reference that opens the context package.

```
🚨 *Handoff* — Ana García
📱 +584145610594
Motivo: handoff_specialist_recommendation · Intención: handoff_specialist_recommendation
Ticket: 4f2a91c8

Quien toma el caso, responde "TOMO" en este grupo.
```

**A case that ended on the clock.** No "TOMO" — the case is over, not up for
grabs. The patient is not told anything; Gutty simply answers them again.

```
⏰ *Caso vencido* — Ana García
📱 +584145610594
Motivo: handoff_specialist_recommendation
Lo tenía Ana y no se cerró. Vuelvo a atender a este paciente.
Ticket: 4f2a91c8
```

**A ticket that could not be opened.** Gutty is *not* muted here, and the message
says so. Do not answer with "TOMO" — there is no row to claim.

```
⚠️ *No pude abrir el ticket* — +584145610594
Motivo: handoff_medical_advice
Ref: 1c0e67c6

El paciente ya tiene respuesta, pero Gutty *no quedó silenciada* y va a seguir
contestándole. Atiendan la conversación directamente.
```

Commands, from a phone in the group's allowlist. The number can be typed the way
it appears on screen — spaces, dashes and parentheses are all fine, and the
country form does not matter (`+52 1 555…` and `+52 555…` reach the same case).

```
@Gutty tomo +58 414 561 0594
@Gutty resume +584145610594
```

---

## The context package

The group is given a reference and nothing else, on purpose: a WhatsApp group has
no retention policy and no erasure path, so the patient's words must not land in
it. The words live here instead, behind the internal API key.

```bash
# The full uuid, not the 8-char prefix. Find it by prefix if that is all you have:
#   select id from handoff_state where id::text like '4f2a91c8%';
curl -s "http://localhost:8083/admin/handoff/$TICKET_ID/context?turns=20" | jq .
```

```jsonc
{
  "ticket":     { "status": "pending", "reason": "...", "claimed_by": null, "expires_at": "..." },
  "patient":    { "phone_e164": "+58…", "wa_id": "58…", "needs_review": false, "known": true },
  "slots": {
    "learned": [],                       // patient_facts — waits on the extractor (F9)
    "derived": { "first_seen": "…", "patient_turns": 4, "returning": true, "last_intent": "…" }
  },
  "history":    [ { "handoff_id": "…", "status": "resumed", "reason": "…" } ],
  "transcript": [ { "direction": "inbound", "text": "…", "at": "…" } ],
  "media":      [ { "reference": "3f9a1c04", "kind": "image", "status": "stored" } ],
  "errors":     []
}
```

Read `errors` first. Sections degrade independently, so an empty `transcript`
with a line in `errors` means a failed read, while an empty one without means
there is genuinely no history — usually a ticket whose patient never reached the
identity registry.

`patient.needs_review` true means two WhatsApp addresses resolved to one number
and nobody has decided whether they are one person. Treat the history as
possibly incomplete.

`media[].reference` is the same 8-character string the asesora was shown when the
patient sent the file, so a receipt in the package can be matched to the message
that carried it.

---

## When something is wrong

**"No tengo handoff activo" for a case you can see in the group.** Since the
canonicalization fix this should be gone. If it happens, compare the stored key
with the typed one — they must be identical:

```sql
select id, contact_phone, status, expires_at from handoff_state
where contact_phone like '%' || right(regexp_replace('<the number>', '\D', '', 'g'), 9);
```

**Gutty is answering a patient an asesora is handling.** Check the window first —
a claimed case runs 24 h from the claim, and past that Gutty resumes by design:

```sql
select status, claimed_by_name, claimed_at, expires_at, expires_at < now() as vencido
from handoff_state where contact_phone = '+58…' order by created_at desc limit 3;
```

**A case expired but the group was never told.** The announcement comes from
agent-core, not crm-adapter. Force a pass and watch the logs:

```bash
curl -s -X POST http://localhost:8083/admin/handoff/sweep      # expire + announce
docker compose logs -f agent-core | grep -i handoff
```

If the sweep reports rows but nothing lands in the group, check
`HANDOFF_TEAM_GROUP_JID` — with it unset the expiry is logged as a warning and
announced to nobody.

**Nothing at all is expiring.** The transition only runs from the sweep, so
confirm the tick is alive: `SWEEPER_INTERVAL_SECONDS` in the environment, and
`sweeper tick failed` in the agent-core logs.

---

## Deploying the OpenClaw plugin

Pre-cutover, OpenClaw is still the live runtime, and its `handoff_human` tool
changed: `contact_phone` is required now. The plugin is installed from the repo
on the host, so a `git pull` alone changes nothing.

```bash
cd /root/nw-agent && git pull --ff-only
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools --force
systemctl --user restart openclaw-gateway.service
openclaw plugins inspect customer-service-tools --runtime --json | jq '.hooks // .runtimeHooks'
```

Without this, the plugin keeps sending phone-less handoffs and crm-adapter now
answers 422 — the escalation fails loudly instead of silently, which is the
intent, but the fix is to ship the plugin, not to relax the endpoint.

---

## A note on test numbers

**Venezuela is the one country where a wa_id and its E.164 form are the same
string.** Every phone fixture in this repo is Venezuelan, which is exactly why
the claim/resume divergence survived a green test suite for months. When
verifying handoff by hand, use a Mexican, Argentine or Brazilian number, or the
test proves only that Venezuela works.
