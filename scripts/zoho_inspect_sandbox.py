"""Inspect what's actually in the Zoho sandbox (Contacts and Deals)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx
from zoho_smoke_test import find_env_file, load_dotenv


def main() -> int:
    env = load_dotenv(find_env_file())
    dc = env.get("ZOHO_DC", "com")
    sandbox = env.get("ZOHO_SANDBOX", "true").lower() == "true"
    api_host = "sandbox.zohoapis" if sandbox else "www.zohoapis"
    api_base = f"https://{api_host}.{dc}/crm/v8"

    # refresh
    resp = httpx.post(
        f"https://accounts.zoho.{dc}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": env["ZOHO_CLIENT_ID"],
            "client_secret": env["ZOHO_CLIENT_SECRET"],
            "refresh_token": env["ZOHO_REFRESH_TOKEN"],
        },
        timeout=15,
    )
    access_token = resp.json()["access_token"]
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    print(f"target: {api_base}\n")

    # Use the GET /Contacts endpoint instead of COQL — works without WHERE
    print("[Contacts] first 5 records:")
    resp = httpx.get(
        f"{api_base}/Contacts",
        headers=headers,
        params={"per_page": 5, "fields": "First_Name,Last_Name,Phone,Email"},
        timeout=15,
    )
    if resp.status_code == 204:
        print("  (empty module — sandbox has zero contacts)")
    elif resp.status_code == 200:
        for r in resp.json().get("data", []):
            print(
                f"  id={r['id']}  "
                f"{r.get('First_Name','')} {r.get('Last_Name','')}  "
                f"phone={r.get('Phone')}  email={r.get('Email')}"
            )
    else:
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}")

    print("\n[Deals] first 3 records:")
    resp = httpx.get(
        f"{api_base}/Deals",
        headers=headers,
        params={"per_page": 3, "fields": "Deal_Name,Stage,Amount,Contact_Name"},
        timeout=15,
    )
    if resp.status_code == 204:
        print("  (empty)")
    elif resp.status_code == 200:
        for r in resp.json().get("data", []):
            print(
                f"  id={r['id']}  name={r.get('Deal_Name')}  "
                f"stage={r.get('Stage')}  amount={r.get('Amount')}  "
                f"contact={r.get('Contact_Name')}"
            )
    else:
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}")

    print("\n[Org info]:")
    resp = httpx.get(f"{api_base}/org", headers=headers, timeout=15)
    if resp.status_code == 200:
        org = resp.json().get("org", [{}])[0]
        print(f"  company={org.get('company_name')}  primary_email={org.get('primary_email')}")
        print(f"  zia_portal_id={org.get('zia_portal_id')}  iso_code={org.get('country_code')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
