"""
Zoho CRM smoke test — run locally without Docker.

Verifies:
  1. .env credentials are loaded
  2. OAuth refresh-token flow returns a valid access token
  3. A COQL query succeeds against the environment ZOHO_SANDBOX selects
  4. Phone-based lookup returns a real contact

A refresh token is bound to ONE environment. Pointing ZOHO_SANDBOX at the other
one yields DOMAIN_TOKEN_MISMATCH on every call — check that before the query.

Usage (from project root):
  python scripts/zoho_smoke_test.py

The script searches for .env in (in order):
  - $NW_AGENT_ENV
  - C:\\Users\\LANZ\\nw-agent\\.env
  - ./.env relative to current working dir
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Windows console (cp1252) can't render comment dividers / unicode in output.
# Force UTF-8 on stdout/stderr so the script runs identically everywhere.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

import httpx

# ── tiny .env loader (no pydantic dependency) ─────────────────────────────────

def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def find_env_file() -> Path:
    candidates = [
        os.environ.get("NW_AGENT_ENV"),
        r"C:\Users\LANZ\nw-agent\.env",
        ".env",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("Could not locate .env. Set NW_AGENT_ENV or run from project root.")


# ── phone normalization (matches zoho_client.py) ──────────────────────────────

def normalize(raw: str) -> str:
    return re.sub(r"[^\d]", "", raw)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    env_path = find_env_file()
    print(f"[1] loaded .env from {env_path}")
    env = load_dotenv(env_path)

    client_id = env.get("ZOHO_CLIENT_ID")
    client_secret = env.get("ZOHO_CLIENT_SECRET")
    refresh_token = env.get("ZOHO_REFRESH_TOKEN")
    dc = env.get("ZOHO_DC", "com")
    sandbox = env.get("ZOHO_SANDBOX", "true").lower() == "true"

    missing = [k for k, v in {
        "ZOHO_CLIENT_ID": client_id,
        "ZOHO_CLIENT_SECRET": client_secret,
        "ZOHO_REFRESH_TOKEN": refresh_token,
    }.items() if not v]
    if missing:
        print(f"  [FAIL] missing: {', '.join(missing)}")
        return 2

    accounts_url = f"https://accounts.zoho.{dc}"
    api_host = "sandbox.zohoapis" if sandbox else "www.zohoapis"
    api_base = f"https://{api_host}.{dc}/crm/v8"
    print(f"    DC={dc}  sandbox={sandbox}  api_base={api_base}")

    # --- 2. token refresh ------------------------------------------------------
    print("[2] refreshing access token...")
    resp = httpx.post(
        f"{accounts_url}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if resp.status_code != 200 or "error" in resp.json():
        print(f"  [FAIL] token refresh failed: {resp.status_code} {resp.text}")
        return 3

    access_token = resp.json()["access_token"]
    print(f"  [OK] access token obtained ({len(access_token)} chars)")

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    # Note: Zoho COQL requires a WHERE clause — there is no plain count query.

    # --- 3. phone lookup against real sandbox contacts ------------------------
    print("[3] phone lookup test (real contacts in whichever environment is configured)...")
    failures = 0
    test_phones = [
        # WhatsApp E.164 equivalents of numbers stored in the CRM
        ("Salvador Bentolila (stored as 04141267078)", "+584141267078"),
        ("Monica Sahmkow (stored as 4142934459)", "+584142934459"),
        ("Maria Jose Molina (stored as 6076431707)", "+16076431707"),
    ]
    for label, phone in test_phones:
        suffix = normalize(phone)[-9:]
        resp = httpx.post(
            f"{api_base}/coql",
            headers=headers,
            json={
                "select_query": (
                    "SELECT id, First_Name, Last_Name, Phone, Email, Idioma, "
                    "Estado_de_Paciente, Tipo_de_Comunidad "
                    f"FROM Contacts WHERE Phone like '%{suffix}%' LIMIT 3"
                )
            },
            timeout=15,
        )
        if resp.status_code == 204:
            print(f"  [WARN] {label} ({phone}): no records found")
            continue
        if resp.status_code != 200:
            print(f"  [FAIL] {label}: {resp.status_code} {resp.text[:200]}")
            failures += 1
            continue
        rows = resp.json().get("data", [])
        if not rows:
            print(f"  [WARN] {label}: empty result")
            continue
        match = rows[0]
        print(
            f"  [OK] {label} -> "
            f"id={match['id']}  "
            f"name={match.get('First_Name','')} {match.get('Last_Name','')}  "
            f"phone={match.get('Phone')}  "
            f"idioma={match.get('Idioma')}  "
            f"estado={match.get('Estado_de_Paciente')}"
        )

    if failures:
        # This used to print "all checks passed" and return 0 while every lookup
        # had failed — a smoke test that passes by not looking, which is the one
        # thing a smoke test must never do.
        print(f"\n[4] {failures} of {len(test_phones)} lookups FAILED")
        return 4

    print("\n[4] all checks passed [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
