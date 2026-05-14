# Agent Bootstrap Debug Plan

> **Audience:** a fresh Claude Code session running on the OpenClaw droplet (`/root/nw-agent`). You have no prior conversation history. Read this top-to-bottom before doing anything. Do not write or commit code unless explicitly instructed below.

## Where you are

- Working directory: `/root/nw-agent` (git checked out, recent commits include Phase 1 intent router build).
- OpenClaw v2026.5.7 running under `systemctl --user`. Service unit: `openclaw-gateway.service`.
- Agent: `nw-cs-agent` (Sonnet 4.6 as of the last config edit).
- WhatsApp test number (the human operator): `+584241329676`.
- Bot's WhatsApp number: `+584123251172`.

## What you need to know before debugging

The repo went through two recent waves of changes:

1. **Liliana → Gutty rename.** The agent persona was renamed across SKILL.md, AGENTS.md, voice doc, eval prompts.
2. **Phase 1 intent router build.** Added `intent_vectors` table, `/v1/classify_intent` endpoint, `classify_intent` plugin tool, and rewrote SKILL.md and AGENTS.md to make the agent route through the classifier on every patient turn. Full plan: [`docs/intent-router-plan.md`](intent-router-plan.md).

After deploying both waves, manual WhatsApp testing kept producing this failure shape on the patient side:

```
"Hola! 🩵\n\nLet me check the handoff state first:"
"I need to read the customer service policy first to understand the proper tool calls:"
"Entendido. Según mis instrucciones, debo verificar primero..."
```

No `customer-service-tools` tool invocation lines appear in the gateway log between inbound and outbound. The classifier endpoint works (99.1% on the intent eval), and the model is Sonnet 4.6 (the swap was finally applied to `agents.defaults.model.primary`). So the issue is NOT the classifier and NOT the model tier.

### The diagnostic smoking gun

Inspect `/root/.openclaw/agents/nw-cs-agent/sessions/sessions.json`. The session snapshot for `agent:nw-cs-agent:main` contains this block:

```json
"skillsSnapshot": {
  "prompt": "\n\nThe following skills provide specialized instructions for specific tasks.\nUse the read tool to load a skill's file when the task matches its description.\n...",
  "skills": [{ "name": "customer-service-policy" }],
  ...
}
```

Two things this proves:

1. **OpenClaw skills are lazy-loaded.** Only the one-line skill *description* is in the system prompt. The actual SKILL.md content is NOT injected — the model has to call a `read` tool to load it. That is why the model emits `"I need to read the customer service policy first..."` — it is literally trying to do that.
2. **The cached description is stale.** It still says `"Liliana persona"` even though the source has been renamed to Gutty. The snapshot was frozen before the rename.

Additionally, `openclaw status` earlier reported:

```
Agents               │ 1 · no bootstrap files · sessions 11 · default nw-cs-agent active just now
```

"**no bootstrap files**" is suspicious. Workspace bootstrap files (eagerly loaded into the system prompt) should normally exist. Either `/root/.openclaw/workspace/AGENTS.md` is not where OpenClaw expects it, or the file isn't registered as a bootstrap.

## Your goal

Make sure the policy the user has been writing (in `openclaw/workspace/AGENTS.md` and `openclaw/skills/customer-service-policy/SKILL.md`) is **actually in the system prompt** the agent receives. Then reset the stale session so the user can re-test from their phone.

Do not change the intent classifier (it works). Do not change the model (it is Sonnet 4.6). Do not change any tool code unless absolutely required.

## Step-by-step

### Step 1 — Read context

```
Read these files first:
- CLAUDE.md
- docs/intent-router-plan.md
- openclaw/workspace/AGENTS.md
- openclaw/skills/customer-service-policy/SKILL.md
```

### Step 2 — Diagnose what's currently loaded

Run these and report what each says:

```bash
# (a) Is the workspace AGENTS.md current?
ls -la /root/.openclaw/workspace/
grep -c "classify_intent" /root/.openclaw/workspace/AGENTS.md
grep -c "Forbidden" /root/.openclaw/workspace/AGENTS.md
grep -c "Gutty" /root/.openclaw/workspace/AGENTS.md
grep -c "Liliana" /root/.openclaw/workspace/AGENTS.md   # want 0

# (b) Compare workspace AGENTS.md vs the repo source — they should be identical
diff /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md

# (c) Where does OpenClaw look for bootstrap files? Check status and config.
openclaw status --deep 2>&1 | grep -iE 'bootstrap|workspace|agents' | head -40
jq '.workspace // .agents // {}' /root/.openclaw/openclaw.json | head -60

# (d) Is the skills directory the gateway loads from up to date?
jq '.skills' /root/.openclaw/openclaw.json
ls -la /root/nw-agent/openclaw/skills/customer-service-policy/
head -20 /root/nw-agent/openclaw/skills/customer-service-policy/SKILL.md

# (e) Current session for the test phone — confirm key shape
jq 'keys[]' /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json | grep 584241329676 || \
  echo "(no live WhatsApp session for that phone — a new one will spawn on next inbound)"

# (f) Sanity: is gateway running, reachable, on Sonnet?
openclaw status 2>&1 | grep -iE 'gateway|model|claude-'
openclaw gateway probe
```

### Step 3 — Investigate OpenClaw's bootstrap convention

Fetch the docs to confirm what counts as a bootstrap file and how to make AGENTS.md eagerly load:

```
WebFetch https://docs.openclaw.ai/agents/bootstrap (or whatever the docs index points to under "bootstrap" / "workspace files")
WebFetch https://docs.openclaw.ai/llms.txt — find the bootstrap / workspace section
```

Look specifically for:
- The expected filename(s) and location(s) for bootstrap content.
- Whether AGENTS.md is one of them or if it should be named differently (`agent.md`, `instructions.md`, `bootstrap.md`, etc.).
- Whether there's a config field that lists bootstrap files explicitly.
- How to make a Skill auto-load (vs. lazy-load) — there may be a flag like `autoload: true` in the frontmatter or a config setting like `skills.alwaysIncluded`.

Report what the docs say before making changes.

### Step 4 — Apply the right fix based on findings

Three possible root causes. Pick the right one based on Step 3:

**Case A: `/root/.openclaw/workspace/AGENTS.md` is stale or missing the new content.**
Fix: copy the current repo version over. Make sure it has the Forbidden behaviors block + the `classify_intent` tool flow.

```bash
cp /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md
```

**Case B: AGENTS.md is the wrong filename for a bootstrap.** OpenClaw expects a different name.
Fix: rename or copy the content into the expected filename in `/root/.openclaw/workspace/`. Reference the doc finding from Step 3.

**Case C: Skills need to be made auto-loading.**
If the docs say there's a config option (e.g. `skills[].autoload: true` or `agents.skills[].always: true`), apply it in `/root/.openclaw/openclaw.json`. Back up the config before editing:

```bash
cp /root/.openclaw/openclaw.json{,.bak.$(date +%Y%m%d-%H%M%S)}
# then jq the right key
```

You may end up needing more than one of A/B/C. Apply each, run `openclaw status` after, and confirm "no bootstrap files" goes away or the agent's `skillsSnapshot.prompt` would change on next session.

### Step 5 — Reset the test phone's session

The current session has the stale "Liliana" snapshot. Force a fresh one:

```bash
# Back up
cp /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json \
   /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json.bak.$(date +%Y%m%d-%H%M%S)

# Find the exact key for the test phone
jq 'keys[]' /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json | grep 584241329676

# Delete only that one (replace <KEY> with what the grep above returned)
jq 'del(."<KEY>")' /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json > /tmp/s.json \
  && mv /tmp/s.json /root/.openclaw/agents/nw-cs-agent/sessions/sessions.json
```

If there is no live key for that phone, skip — a new session will spawn on the next inbound.

### Step 6 — Restart and verify

```bash
systemctl --user restart openclaw-gateway.service
sleep 10
openclaw status 2>&1 | head -40
openclaw gateway probe
```

Confirm:
- Gateway is `Reachable: yes` on the probe.
- Status shows `default claude-sonnet-4-6`.
- "no bootstrap files" is gone if you fixed Case B/C (a real number > 0 should appear, or the line shouldn't say "no").
- No new errors in `openclaw logs --follow` (tail for 20 lines, then stop).

### Step 7 — Hand off

Stop here. Report to the user with:

1. What was wrong (which Case(s) applied).
2. What you fixed (which files / config keys changed).
3. Whether `openclaw status` looks healthy.
4. The exact phrase the user should send from their phone to test:

> Necesito que me recomiendes un especialista, tengo gastritis crónica

Tell the user to watch for, in `openclaw logs --follow`:
- A `customer-service-tools` invocation line (or `tool_invoke` line naming `check_handoff_state`, `classify_intent`, `handoff_human`)
- ONE Spanish reply to the patient (no English narration like "Let me check..." or "I need to read...")

And to verify the state row was written:

```bash
INTERNAL_API_KEY=$(grep '^INTERNAL_API_KEY=' /root/nw-agent/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8082/v1/handoff/state/check \
  -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  -H "content-type: application/json" \
  -d '{"contact_phone":"+584241329676"}' | jq .
```

Want `"active": true, "status": "pending"`.

## Constraints — things NOT to do

- **Do not commit code changes** to the repo. All fixes here are server-side state (workspace files, openclaw.json, sessions.json).
- **Do not change the agent model** — it is Sonnet 4.6 and should stay there.
- **Do not modify the intent classifier, seeds, plugin tools, or rag-api code.** The classifier is at 99.1% accuracy. Not the bottleneck.
- **Do not send the WhatsApp test message yourself** — the user does this from their phone.
- **Do not bypass the duplicate-plugin warning** about `customer-service-tools` — it is benign (config-selected plugin overrides global, intentional).
- **Always back up before editing** `openclaw.json` or `sessions.json`. Both are easy to corrupt with a wrong jq path.

## If you get stuck

If Step 3 docs don't clearly explain bootstrap files, try the OpenClaw CLI for hints:

```bash
openclaw --help 2>&1 | grep -iE 'workspace|bootstrap|skill'
openclaw skills --help 2>&1
openclaw config --help 2>&1
openclaw doctor 2>&1 | head -40   # may flag the bootstrap issue directly
```

If `openclaw doctor` reports a fixable problem, suggest the fix to the user before applying `--fix` (the auto-fix may rewrite parts of `openclaw.json` you don't want changed).

## Success criteria

You are done when:

1. `openclaw status` is healthy, on Sonnet 4.6, no glaring red.
2. The workspace AND/OR skill content reaches the agent eagerly (you have evidence — either a non-zero bootstrap file count, an `alwaysIncluded` skill setting, or by reading a fresh session snapshot after a test).
3. The stale Liliana-named session for the test phone is gone or replaced.
4. The user has clear instructions for what to test next.
