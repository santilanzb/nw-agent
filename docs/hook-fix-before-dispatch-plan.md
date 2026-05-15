# Hook Fix — switch `inbound_claim` to `before_dispatch`

> **Audience:** a fresh Claude Code session executing this without prior conversation context. Read top-to-bottom before doing anything. This is a small, scoped change — server-state + ~10 lines of plugin code, no architecture rewrite.

## Why this exists

The `inbound_claim` hook we registered in `openclaw/plugins/customer-service-tools/index.js` does load (we confirmed `register() called` fires) but never executes on real WhatsApp inbound messages. Research into the OpenClaw v2026.5.7 dispatch pipeline (cited file: `src/auto-reply/reply/dispatch-from-config.ts`) reveals:

- `inbound_claim` is a **targeted** hook that only fires when an inbound message is destined for a conversation already explicitly bound to a plugin (sub-agent sessions). It is not broadcast to general observers. For a "non-capability" tool plugin like ours, on a regular WhatsApp DM, `inbound_claim` is **silently skipped** by design.
- The correct hook for gating the agent before LLM invocation is **`before_dispatch`** — a blocking "decision" hook that the Gateway awaits before dispatching to the agent. Its handler can return `{ handled: true, text?: string }` to short-circuit the agent run, with or without sending a reply.
- Without the `plugins.entries.<id>.hooks.allowConversationAccess: true` flag, non-bundled plugins receive empty `event.content` in conversation-level hooks — a privacy gate.

The fix is three small things: swap the hook name, swap the result-payload shape, and set the permission flag. No backend rewrite. Backends (rag-api, crm-adapter, intent classifier) are unchanged.

## Current vs target

### Current (broken on WhatsApp inbound)

```javascript
api.on("inbound_claim", async (event) => {
  if (event.isGroup) return { handled: false };
  const phone = event.senderId;
  // ...
  return { handled: true, reply: { text: phrase } };
});
```

### Target (per Gemini research, citing OpenClaw v2026.5.7 source)

```javascript
api.on("before_dispatch", async (event) => {
  // Filter to WhatsApp channel only — let other channels through to LLM
  if (event.channel !== "whatsapp") return { handled: false };
  if (event.isGroup) return { handled: false };
  const phone = event.senderId ?? event.from;
  // ...
  return { handled: true, text: phrase };  // <-- "text", not "reply: { text }"
});
```

The exact event-field names (`senderId` vs `from`, `isGroup` presence, etc.) MUST be verified against the SDK type definitions before code changes — see Step 1.

## What "done" looks like

1. The hook handler fires on the next WhatsApp inbound message from the test phone (`+584241329676`), proven by HTTP requests to `/v1/handoff/state/check`, `/v1/classify_intent`, and `/v1/handoff` appearing in the rag-api and crm-adapter container logs.
2. The patient receives **one** Spanish handoff phrase. No English narration. No LLM-composed reply.
3. `openclaw plugins inspect customer-service-tools --runtime --json` shows the `before_dispatch` hook registered in live Gateway memory.
4. `handoff_state` row written with `status=pending` for the test phone.
5. Follow-up messages from the same phone get no reply (silent mute by hook).
6. FAQ test ("qué planes tienen?") gets the canned WhatsApp-native plans response without a `model_call` log.

## Step-by-step

### Step 1 — Verify the SDK event and result types BEFORE editing code

Hard requirement. Do not guess field names.

```bash
# Find the PluginHookBeforeDispatchEvent and PluginHookBeforeDispatchResult definitions
grep -rn "PluginHookBeforeDispatchEvent\|PluginHookBeforeDispatchResult\|PluginHookBeforeDispatchContext" \
  /usr/lib/node_modules/openclaw/dist/plugin-sdk/ | head -20

# Look at the hook-types.d.ts for these types specifically
grep -A 25 "PluginHookBeforeDispatchEvent" \
  /usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts

grep -A 15 "PluginHookBeforeDispatchResult" \
  /usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts
```

Record these answers from the output (paste them into your reasoning so the user can review):

- Is the channel identifier on `event.channel`, `event.channelId`, or elsewhere? What value does WhatsApp use? (Most likely `"whatsapp"` or `"channels/whatsapp"`.)
- What is the field name for the sender phone? (`senderId`, `from`, `metadata.senderId`?)
- Is `isGroup` a top-level field, or is it under `metadata`, or do we infer from `chatId` / `jid` ending in `@g.us`?
- What is the field name for the message body? `content`, `body`, `text`?
- Is `conversationId` a top-level field?
- What does the result type look like? Specifically: is the reply text on `text`, `reply`, `replies[]`, or another field?

If any of those answers differ from what the Gemini research described (`event.channel`, `event.content`), use the **actual SDK definitions** — do not trust the research report's field names. The research was right about the hook semantics; field names should be verified.

### Step 2 — Apply the code changes

Edit `openclaw/plugins/customer-service-tools/index.js`. The whole hook handler is roughly lines 122–197.

Make these changes:

1. Replace `api.on("inbound_claim", async (event) => {` with `api.on("before_dispatch", async (event) => {`.
2. Update the comment block above it to reflect the new hook name and reasoning.
3. Add a channel filter at the top: if `event.channel !== "whatsapp"` (or whatever the verified field is), return `{ handled: false }`. This prevents the hook from gating non-WhatsApp channels.
4. Update all `return { handled: true, reply: { text: phrase } };` to `return { handled: true, text: phrase };`.
5. Update the FAQ branch similarly: `return { handled: true, text: faqText };`.
6. The acknowledgment silent branch stays `return { handled: true };` (no text → silent block).
7. Use the verified field names for `phone`, `isGroup`, `event.content`, `event.conversationId`, `event.senderName` from Step 1. If any field is on `event.metadata`, dot through it.

Keep the `console.log("[customer-service-tools] register() called")` at the top of `register(api)` — we still want it.

Run `python -m pytest tests/ -q` and `python -m ruff check .` to confirm no Python regressions. (The Python side doesn't depend on the hook, but verify.)

### Step 3 — Set the `allowConversationAccess` permission flag

The plugin will receive an empty `event.content` without this flag. Set it in `openclaw.json` on the droplet. Since the build agent may be running on Windows, write the command for the user to run on the droplet:

```bash
# On the droplet
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.$(date +%Y%m%d-%H%M%S)
jq '.plugins.entries["customer-service-tools"].hooks = { allowConversationAccess: true }' \
  ~/.openclaw/openclaw.json > /tmp/oc.json \
  && mv /tmp/oc.json ~/.openclaw/openclaw.json
chmod 600 ~/.openclaw/openclaw.json

# Verify
jq '.plugins.entries["customer-service-tools"]' ~/.openclaw/openclaw.json
```

The expected output should include both the previous `enabled: true` and the new `hooks: { allowConversationAccess: true }` block.

If the openclaw CLI version supports it, the same change can be made via:

```bash
openclaw config set 'plugins.entries.customer-service-tools.hooks.allowConversationAccess' true
```

Either path is fine.

### Step 4 — Commit and push

Two commits is good — keeps the diff readable:

1. **Commit A**: Plugin code change (the hook swap). Message body should explain the inbound_claim-vs-before_dispatch distinction so future readers don't repeat the mistake.
2. **Commit B**: Update `CLAUDE.md` and/or `docs/intent-router-plan.md` to note: deploy step now includes `--force` plugin install (the canonical install path is `~/.openclaw/extensions/customer-service-tools/`, sourced from the git tree), and the `allowConversationAccess` permission flag. Also add a one-line "How to verify hooks are actually registered" note pointing at `openclaw plugins inspect <id> --runtime --json`.

Run lint + tests before each commit. Push at the end.

### Step 5 — Deploy commands (write these as a script the user can run on the droplet)

Write this as a comment block in your final summary message, OR commit a `scripts/deploy_plugin.sh` if you think a script is more useful (one-line guard: don't run if not on the droplet). The deploy sequence:

```bash
cd /root/nw-agent
git pull --ff-only

# Set the allowConversationAccess flag if not already (idempotent)
jq '.plugins.entries["customer-service-tools"].hooks = { allowConversationAccess: true }' \
  ~/.openclaw/openclaw.json > /tmp/oc.json \
  && mv /tmp/oc.json ~/.openclaw/openclaw.json
chmod 600 ~/.openclaw/openclaw.json

# Reinstall the plugin so the extensions/ copy picks up the new index.js
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools --force

# Restart
systemctl --user restart openclaw-gateway.service
sleep 12

# Verify the new hook is registered in runtime memory
openclaw plugins inspect customer-service-tools --runtime --json | jq '.hooks // .runtimeHooks'
# Want: an entry naming "before_dispatch"
```

### Step 6 — Hand off to user for the WhatsApp test

Do NOT send the WhatsApp test yourself. Stop here. Tell the user:

1. The fix is pushed; deploy commands are in [docs/hook-fix-before-dispatch-plan.md](hook-fix-before-dispatch-plan.md) (this file) under "Deploy commands".
2. After deploy, run `openclaw plugins inspect customer-service-tools --runtime --json | jq '.hooks // .runtimeHooks'` and paste the result so we can confirm the hook is live.
3. Then send the gastritis WhatsApp message and watch the rag-api / crm-adapter container logs (`docker logs cs-agent-rag-api --since 2m 2>&1 | tail -20` and same for `cs-agent-crm-adapter`). The hook firing is proven by `/v1/handoff/state/check`, `/v1/classify_intent`, and `/v1/handoff` HTTP requests appearing in those logs.

## Constraints

- **Do NOT change** the intent classifier, seeds, crm-adapter, rag-api, or the Postgres schema. The fix is purely orchestration-layer.
- **Do NOT change** the agent model, OpenClaw config beyond the `hooks.allowConversationAccess` flag, or any session state.
- **Do NOT** add a parallel `inbound_claim` handler "just in case". Remove the inbound_claim registration cleanly — keeping both registered could cause subtle conflicts.
- **Do NOT** send WhatsApp test messages yourself. The user has the test phone and will do the manual test after deploy.
- **If the SDK type lookups in Step 1 reveal that `before_dispatch` has materially different semantics from what's documented in this plan** (e.g., it's also targeted-only, or doesn't support `handled: true`), stop and report. Don't guess your way through.

## Rollback

If `before_dispatch` also fails to fire or doesn't block the agent:

```bash
git revert <hook-fix-commit-sha>
git push
# On droplet:
cd /root/nw-agent && git pull --ff-only
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools --force
systemctl --user restart openclaw-gateway.service
```

The revert restores the previous `inbound_claim` registration. The `allowConversationAccess` flag in openclaw.json is benign — it can stay set even after revert.

## Reading list

Files the build agent should read before writing code:

- [openclaw/plugins/customer-service-tools/index.js](../openclaw/plugins/customer-service-tools/index.js) — current plugin code with the inbound_claim hook
- `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts` — exact types for `PluginHookBeforeDispatchEvent`, `PluginHookBeforeDispatchResult`, `PluginHookBeforeDispatchContext`
- [docs/intent-router-plan.md](intent-router-plan.md) — Phase 1 plan background, classifier semantics
- [docs/agent-core-plan.md](agent-core-plan.md) — Phase 2 plan, deterministic-dispatch architecture and the dispatch map
- [docs/architecture-diagrams.md](architecture-diagrams.md) — the inbound decision tree
- [docs/agent-bootstrap-debug-plan.md](agent-bootstrap-debug-plan.md) — context on what was previously diagnosed

The Gemini-research source that justifies this fix is referenced inline in the "Why this exists" section of this document. Key citations: `src/auto-reply/reply/dispatch-from-config.ts` (the `pluginOwnedBinding` branch that gates `inbound_claim`), unmerged PR #49875 (proposed broadcast fix), and the `PluginHookBeforeDispatchResult` type contract.
