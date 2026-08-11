#!/usr/bin/env python3
"""
Phase 1 smoke test — §9 Stage 2 of the NutriWhite Brain plan.

Sends the 6 test messages through agent-core's webhook endpoint directly,
bypassing WAHA, to verify the state machine behaves correctly.

Usage:
    pip install httpx psycopg[binary]
    python scripts/smoke_test_phase1.py

Environment variables (or .env file):
    AGENT_CORE_URL   default: http://localhost:8083
    WAHA_HOOK_HMAC_KEY   required for HMAC signing
    DATABASE_URL          to verify turn_log rows
    TEST_PHONE            E.164 test number, default: +15550001234
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import httpx  # noqa: E402

AGENT_CORE_URL = os.environ.get("AGENT_CORE_URL", "http://localhost:8083")
HMAC_KEY = os.environ.get("WAHA_HOOK_HMAC_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://agent:agent@localhost:5432/company_agent")
TEST_PHONE = os.environ.get("TEST_PHONE", "+15550001234")
TEAM_GROUP_JID = os.environ.get("HANDOFF_TEAM_GROUP_JID", "")


def sign(body: bytes, key: str) -> str:
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


def waha_msg(
    phone: str,
    text: str,
    msg_id: str | None = None,
    is_group: bool = False,
    group_jid: str | None = None,
    participant_phone: str | None = None,
) -> dict:
    if msg_id is None:
        msg_id = str(uuid.uuid4())
    from_jid = (group_jid or phone.lstrip("+") + "@g.us") if is_group else (phone.lstrip("+") + "@c.us")
    payload: dict = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": msg_id,
            "from": from_jid,
            "fromMe": False,
            "body": text,
            "timestamp": int(time.time()),
            "isGroup": is_group,
            "type": "chat",
        },
    }
    if is_group and participant_phone:
        payload["payload"]["participant"] = participant_phone.lstrip("+") + "@c.us"
    return payload


def post_webhook(data: dict) -> httpx.Response:
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if HMAC_KEY:
        headers["X-Webhook-Hmac"] = sign(body, HMAC_KEY)
    with httpx.Client(timeout=30) as client:
        return client.post(f"{AGENT_CORE_URL}/webhooks/waha", content=body, headers=headers)


def check_turn_log(expected_intent: str, expected_outcome: str) -> dict | None:
    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT classified_intent, decision, task_outcome, handoff_fired,
                       composed_by_llm, reply_text, latency_ms
                FROM turn_log
                ORDER BY created_at DESC
                LIMIT 1
                """,
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:  # noqa: BLE001 - smoke test reports any failure as [FAIL]
        return {"error": str(e)}


def pass_fail(cond: bool) -> str:
    return "✅ PASS" if cond else "❌ FAIL"


def run() -> int:
    print(f"\n{'='*60}")
    print("Phase 1 Smoke Test — NutriWhite Brain")
    print(f"agent-core: {AGENT_CORE_URL}")
    print(f"test phone: {TEST_PHONE}")
    print(f"{'='*60}\n")

    failures = 0

    # ── Health check ──────────────────────────────────────────────────────────
    print("0. Health check ...")
    with httpx.Client(timeout=10) as client:
        r = client.get(f"{AGENT_CORE_URL}/health")
    ok = r.status_code == 200
    print(f"   {pass_fail(ok)} status={r.status_code} body={r.text[:100]}")
    if not ok:
        print("   FATAL: agent-core not reachable — aborting")
        return 1

    # ── Test 1: FAQ — qué planes tienen ──────────────────────────────────────
    print("\n1. Send 'qué planes tienen?' → expect faq_consultation_plans, deterministic")
    r = post_webhook(waha_msg(TEST_PHONE, "qué planes tienen?"))
    print(f"   webhook status={r.status_code}")
    time.sleep(3)
    row = check_turn_log("faq_consultation_plans", "replied")
    if row and "error" not in row:
        ok = row.get("classified_intent") == "faq_consultation_plans" and not row.get("composed_by_llm")
        print(f"   {pass_fail(ok)} intent={row.get('classified_intent')} composed={row.get('composed_by_llm')} outcome={row.get('task_outcome')}")
    else:
        print(f"   ❌ FAIL could not read turn_log: {row}")
        ok = False
    if not ok:
        failures += 1

    # ── Test 2: Handoff — specialist recommendation ───────────────────────────
    print("\n2. Send 'Necesito un especialista, tengo gastritis' → expect handoff")
    r = post_webhook(waha_msg(TEST_PHONE + "2", "Necesito un especialista, tengo gastritis"))
    print(f"   webhook status={r.status_code}")
    time.sleep(3)
    row = check_turn_log("handoff_specialist_recommendation", "handoff")
    if row and "error" not in row:
        ok = row.get("handoff_fired") is True and row.get("task_outcome") == "handoff"
        print(f"   {pass_fail(ok)} intent={row.get('classified_intent')} handoff_fired={row.get('handoff_fired')} outcome={row.get('task_outcome')}")
    else:
        print(f"   ❌ FAIL could not read turn_log: {row}")
        ok = False
    if not ok:
        failures += 1

    HANDOFF_PHONE = TEST_PHONE + "2"

    # ── Test 3: Mute — follow-up while handoff active ─────────────────────────
    print("\n3. Follow-up message → expect silent (muted)")
    r = post_webhook(waha_msg(HANDOFF_PHONE, "Hola? sigo aquí"))
    print(f"   webhook status={r.status_code}")
    time.sleep(3)
    row = check_turn_log(None, "silent")
    if row and "error" not in row:
        ok = row.get("task_outcome") == "silent"
        print(f"   {pass_fail(ok)} outcome={row.get('task_outcome')} task={row.get('task')}")
    else:
        print(f"   ❌ FAIL could not read turn_log: {row}")
        ok = False
    if not ok:
        failures += 1

    # ── Test 4: Group resume command ──────────────────────────────────────────
    if TEAM_GROUP_JID:
        print(f"\n4. Group @Gutty resume {HANDOFF_PHONE} → expect handoff closed")
        group_msg = waha_msg(
            HANDOFF_PHONE,
            f"@Gutty resume {HANDOFF_PHONE}",
            is_group=True,
            group_jid=TEAM_GROUP_JID,
            participant_phone="+584120000001",
        )
        r = post_webhook(group_msg)
        print(f"   webhook status={r.status_code}")
        time.sleep(2)
        # Verify: send another message — should no longer be muted
        post_webhook(waha_msg(HANDOFF_PHONE, "hola"))
        time.sleep(3)
        row = check_turn_log(None, None)
        if row and "error" not in row:
            ok = row.get("task_outcome") != "silent"
            print(f"   {pass_fail(ok)} after resume, outcome={row.get('task_outcome')}")
        else:
            print(f"   ❌ FAIL could not read turn_log: {row}")
            ok = False
        if not ok:
            failures += 1
    else:
        print("\n4. SKIP — HANDOFF_TEAM_GROUP_JID not set (set it in .env to test group resume)")

    # ── Test 5: Clarify — ambiguous message ───────────────────────────────────
    print("\n5. Send ambiguous message → expect clarify + LLM compose (Sonnet)")
    r = post_webhook(waha_msg(TEST_PHONE + "5", "necesito información"))
    print(f"   webhook status={r.status_code}")
    time.sleep(6)
    row = check_turn_log(None, "replied")
    if row and "error" not in row:
        ok = row.get("decision") in ("clarify", "fallback_llm") and row.get("composed_by_llm")
        print(f"   {pass_fail(ok)} decision={row.get('decision')} composed={row.get('composed_by_llm')} model={row.get('model_used')}")
        if row.get("reply_text"):
            print(f"   reply preview: {row['reply_text'][:120]!r}")
    else:
        print(f"   ❌ FAIL could not read turn_log: {row}")
        ok = False
    if not ok:
        failures += 1

    # ── Test 6: English → handoff_english ─────────────────────────────────────
    print("\n6. Send English message → expect handoff_english")
    r = post_webhook(waha_msg(TEST_PHONE + "6", "Hello I need information about your plans"))
    print(f"   webhook status={r.status_code}")
    time.sleep(3)
    row = check_turn_log("handoff_english", "handoff")
    if row and "error" not in row:
        ok = row.get("classified_intent") == "handoff_english" and row.get("handoff_fired")
        print(f"   {pass_fail(ok)} intent={row.get('classified_intent')} handoff={row.get('handoff_fired')}")
    else:
        print(f"   ❌ FAIL could not read turn_log: {row}")
        ok = False
    if not ok:
        failures += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = (6 if TEAM_GROUP_JID else 5) - failures
    total = 6 if TEAM_GROUP_JID else 5
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed   failures={failures}")
    if failures == 0:
        print("✅ Phase 1 smoke test PASSED")
    else:
        print("❌ Phase 1 smoke test FAILED")
    print(f"{'='*60}\n")
    return failures


if __name__ == "__main__":
    sys.exit(run())
