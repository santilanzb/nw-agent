# Phase 3 — Active team-group push on handoff fire

> **Audience:** a fresh Claude Code session executing this without prior conversation context. Read top-to-bottom before doing anything. This is server-state + plugin code changes; backend services are not touched.

## Why this exists

Phase 2 deployed a `before_dispatch` hook that deterministically catches handoff intents on inbound WhatsApp messages, writes a `handoff_state` row, and replies to the patient with the canned Spanish handoff phrase. **However, the logistics team is not actively notified** — they have to learn about the new handoff by either watching the Zoho CRM for new Notes on Contacts or hearing about it out-of-band.

Phase 3 closes that loop: when a handoff fires, the bot should push a structured WhatsApp message into the "Gutty Agent" group with the three operators (Maria, two others — phone numbers in [docs/intent-router-plan.md](intent-router-plan.md)). First-to-claim model — whoever responds `@Gutty tomo +58...` in the group owns the case.

The previous obstacle was an undiscovered OpenClaw outbound-send API for sending a message to an arbitrary JID. Hooks can `return { handled: true, text: "..." }` to send a reply to the originating chat, but that only replies to the patient — it can't push to a different chat (the team group). This plan starts with the discovery, then wires the team push.

## What "done" looks like

1. When the `before_dispatch` hook executes a `handoff_human` dispatch, it POSTs a notification message to the "Gutty Agent" WhatsApp group. Format:

   ```
   🚨 Handoff: <patient_name or contact_phone>
   📱 <contact_phone>
   Motivo: <reason from dispatch.params>
   Última pregunta: "<patient message>"
   Zoho: <contact_id link if known>
   Quien toma el caso, responde "TOMO" en este grupo.
   ```

2. The group JID is configured once in `~/.openclaw/openclaw.json` as `channels.whatsapp.handoffTeamGroupJid` (or similar — pick the canonical key after the SDK lookup in Step 1).

3. Existing patient-side behavior is unchanged. Same handoff phrase, same `handoff_state` row, same mute on subsequent patient messages.

4. If the team-group push fails (network blip, JID stale, whatever), the patient-side reply still goes out. The push failure is logged at `error` level but does not block the patient experience.

5. The intent-router plan's Phase 3 box gets checked. The architecture diagrams' "🔴 Not yet built — Active push to team group on handoff fire" line moves to 🟢.

## Step-by-step

### Step 1 — Discover the OpenClaw outbound-send API

Hard requirement. Do not guess at API surfaces. Look at what the WhatsApp plugin exports and what the gateway's plugin SDK exposes for sending a message to an arbitrary JID.

```bash
# (a) What does the WhatsApp plugin export for outbound send?
ls /root/.openclaw/npm/node_modules/@openclaw/whatsapp/dist/
grep -lrE "sendMessage|sendText|deliverMessage|sendOutbound|sendToJid" \
  /root/.openclaw/npm/node_modules/@openclaw/whatsapp/dist/

# (b) Look at the plugin SDK for "send" / "outbound" / "deliver" methods exposed to plugins
grep -rnE "sendOutbound|sendMessage|sendReply|deliverReply|sendToChannel" \
  /usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/types.d.ts \
  | head -30

# (c) Check the gateway methods exposed to plugins for cross-channel send
grep -rnE "gatewayMethod|registerGatewayMethod|channels\." \
  /usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/types.d.ts \
  | head -20

# (d) Is there an HTTP endpoint on the gateway for sending a message?
grep -rnE "POST.*send|outbound.*POST|/v1/send|/v1/message" \
  /usr/lib/node_modules/openclaw/dist/ 2>/dev/null | head -20

# (e) Or does the WhatsApp plugin expose its own HTTP endpoint?
grep -rE "registerHttpRoute|registerHttp" \
  /root/.openclaw/npm/node_modules/@openclaw/whatsapp/dist/ 2>/dev/null | head -10
```

Report back what each command surfaces. Specifically I need:

- **Exact function name** for sending a message to a JID (e.g. `api.channels.whatsapp.sendMessage(jid, text)`).
- **Whether the function is available inside a hook callback** (`api` is the same `api` object the hook closure has).
- **The signature** — does it take `{ jid, text }` or positional? Does it return a Promise?
- **Error semantics** — does it throw on failure or return a status?

If (a)-(e) don't surface an answer, try (f):

```bash
# (f) Look at the gateway loopback API endpoints for send actions
curl -s http://127.0.0.1:18789/__openclaw__/api 2>&1 | head -40
openclaw gateway methods 2>&1 | head -40
openclaw help 2>&1 | grep -iE "send|outbound|message" | head -10
```

### Step 2 — Discover the "Gutty Agent" group JID

The OpenClaw WhatsApp plugin presumably tracks groups it's a member of. We need the JID (format: `120363xxxxxx@g.us`).

```bash
# (a) Look at WhatsApp plugin's persisted state for known groups
ls /root/.openclaw/credentials/whatsapp* /root/.openclaw/identity/whatsapp* 2>/dev/null
find /root/.openclaw -name "*.json" 2>/dev/null | xargs grep -l "g.us" 2>/dev/null | head -5

# (b) Does OpenClaw have a CLI to list groups?
openclaw whatsapp --help 2>&1 | head -30
openclaw channels --help 2>&1 | head -20

# (c) From the message journal — any inbound from a group?
grep -E '"isGroup":\s*true|@g.us' /root/nw-agent/runtime/openclaw-message-journal.jsonl 2>/dev/null | head -3

# (d) Fall back: the team can post once in the group, capture the inbound event,
#     and read the chat/group JID from event.metadata.chatId or similar.
```

The cleanest path is probably (d) — have the team send a single hello message from inside the group (`@Gutty test`), capture the JID from the gateway log, and record it in `openclaw.json`. Document this in Step 4.

### Step 3 — Wire the hook to push to the team group

In `openclaw/plugins/customer-service-tools/index.js`, inside the `before_dispatch` handler in the `if (dispatch?.tool === "handoff_human")` branch. After the `postJsonWithRetry(.../v1/handoff, ...)` call, before returning the patient reply, push the team notification.

Pseudo-code (build it against the actual API surface from Step 1):

```javascript
// After the /v1/handoff call succeeds (or even if it fails)
try {
  const teamJid = process.env.HANDOFF_TEAM_GROUP_JID  // pulled from openclaw.json via env-substitution
    ?? api.pluginConfig?.handoffTeamGroupJid;
  if (teamJid) {
    const notif =
      "🚨 *Handoff* — " + (event.senderName ?? phone) + "\n" +
      "📱 " + phone + "\n" +
      "Motivo: " + (dispatch.params?.reason ?? intent) + "\n" +
      "Última pregunta: \"" + event.content + "\"\n\n" +
      "Quien toma el caso, responde \"@Gutty tomo " + phone + "\" en este grupo.";

    // EXACT FUNCTION CALL TBD from Step 1 discovery.
    // Examples of shapes to try:
    //   await api.channels.whatsapp.sendMessage({ jid: teamJid, text: notif });
    //   await api.sendMessage({ channel: "whatsapp", to: teamJid, text: notif });
    //   await fetch(`http://127.0.0.1:18789/__openclaw__/channels/whatsapp/send`, ...);
  }
} catch (err) {
  // Push failure does NOT block patient-side reply. Log loudly so the
  // missed-reply watchdog or oncall can see we have a notification gap.
  console.error("[nw-hook] team-group push failed:", err.message);
}

// (continue with existing) return { handled: true, text: phrase };
```

Three rules during implementation:

1. **Never make the team push block the patient reply.** Use try/catch and continue. The patient gets their handoff phrase regardless.
2. **Never include patient PII in the team message beyond first name + phone + reason + the patient's last message.** No prior history, no plan details, no Zoho data dump.
3. **Be idempotent on retry.** If the team push fails and the patient sends another message that re-fires a handoff, the new handoff supersedes the old one (existing `handoff_state.create` already does this with the "close prior active" UPDATE).

### Step 4 — Configure the group JID

Add a new field to the openclaw.json plugin config:

```bash
# Replace <JID> with the actual JID captured in Step 2
jq '.plugins.entries["customer-service-tools"].config.handoffTeamGroupJid = "<JID>"' \
  ~/.openclaw/openclaw.json > /tmp/oc.json && mv /tmp/oc.json ~/.openclaw/openclaw.json
chmod 600 ~/.openclaw/openclaw.json
```

If the chosen API takes the JID directly from a gateway-level config rather than per-plugin, adjust accordingly.

Also update [.env.example](../.env.example) to document the new variable so anyone bootstrapping a fresh droplet knows it exists.

### Step 5 — Test plan

After deploy:

1. **From a clean state** (resume the existing handoff first), send the gastritis message from `+584241329676`.
2. **Patient side**: Spanish handoff phrase appears. (Existing behavior — should still work.)
3. **Team group side**: the structured handoff notification appears in the "Gutty Agent" group within ~2 seconds. All three operators see it.
4. **One operator types `@Gutty tomo +584241329676` in the group.** The existing `team_claim_handoff` flow (still routed through the LLM because group commands aren't yet in the hook) marks state as `claimed`.
5. **Patient sends another message.** Silent — mute still works (existing behavior).
6. **Operator types `@Gutty resume +584241329676`.** State clears. Patient can talk to Gutty again.

If step 3 fails (team group sees nothing), check the gateway log for `[nw-hook] team-group push failed` lines. Common causes:
- JID format wrong (must be `120363...@g.us`, not a phone number)
- Bot not actually a member of the group
- Bot was removed from the group post-pairing
- API method signature mismatch from Step 1

### Step 6 — Commit and push

One or two commits is fine:

1. Plugin code change with the team-push logic and JID resolution.
2. (Optional) `.env.example` + a short note in CLAUDE.md / docs/architecture-diagrams.md flipping the 🔴 to 🟢 for "Active push to team group on handoff fire".

Run lint + tests before each commit.

## Constraints

- **Do not modify** the intent classifier, seeds, crm-adapter, rag-api, Postgres schema, or `handoff_state` table.
- **Do not change** the patient-facing behavior. Same phrase, same mute, same state.
- **Never PII-leak** into the team group. First name + phone + reason + last message only.
- **Push must be best-effort.** Patient flow continues even if push fails.
- **Verify the API surface in Step 1 before writing code.** If discovery doesn't surface a clean send-to-JID method, stop and report — we may need to fall back to using an external WhatsApp send library (whatsapp-web.js etc.) rather than the OpenClaw plugin, which is a different and bigger change.

## If discovery fails

If Step 1 surfaces no usable outbound-send API:

- Document what you tried and what each command returned.
- Do not blindly hardcode a fetch to a guessed URL.
- The fallback is to write a small Node sidecar that uses whatsapp-web.js or Baileys directly to push to the team group on a webhook from crm-adapter. That's a meaningful chunk of work — stop and tell the user before starting.

## Rollback

If team-push breaks the patient flow somehow:

```bash
git revert <phase-3-commit-sha>
git push
# On droplet:
cd /root/nw-agent && git pull --ff-only
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools --force
systemctl --user restart openclaw-gateway.service
```

The Phase 2 patient-side flow is restored. The JID config in openclaw.json is benign; it can stay set.

## Reading list

Files to read before writing code:

- [openclaw/plugins/customer-service-tools/index.js](../openclaw/plugins/customer-service-tools/index.js) — current hook implementation; the handoff branch is where the new push goes
- [docs/intent-router-plan.md](intent-router-plan.md) — Phase 1 plan + team phone numbers
- [docs/agent-core-plan.md](agent-core-plan.md) — Phase 2 plan + hook architecture
- [docs/hook-fix-before-dispatch-plan.md](hook-fix-before-dispatch-plan.md) — Phase 2 hook switch (event/result types)
- [docs/architecture-diagrams.md](architecture-diagrams.md) — system overview + reliability scorecard
- `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/types.d.ts` — plugin API surface
- `/root/.openclaw/npm/node_modules/@openclaw/whatsapp/dist/` — WhatsApp plugin internals; this is where the send-to-JID method most likely lives
