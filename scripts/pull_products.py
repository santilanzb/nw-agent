"""
Pull the active product catalogue from Zoho into facts/prices.yaml.

Graft G2. The prices Gutty quotes were hardcoded in two places and drifted out of
Zoho: on 2026-08-11 both surfaces were still quoting a $229 plan that had been
`Product_Active: false` for some time, and the corpus the retriever reads was
quoting it too. Prices are data, so they come from the system of record.

**Keyed on the Zoho record id, not Product_Code.** Verified live: ~60% of active
products have a null `Product_Code`, and codes repeat across active rows at
different prices (`PLAN-MANT-1CONS-FULL-01` is both $149 and $135). The code is
carried as a display field and its hygiene is reported for calidad@, never used
as a key.

**F&F rows are excluded from what Gutty may quote.** Every family has a
friends-and-family variant at a lower price; an unqualified discount offered by a
bot is a revenue leak with no audit trail. They are still written to the file,
flagged, so the exclusion is auditable rather than invisible.

Usage (from the project root):
    python scripts/pull_products.py            # write facts/prices.yaml
    python scripts/pull_products.py --check    # exit 1 if the file is stale
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml

from company_agent.crm_adapter import coql
from company_agent.crm_adapter.config import CrmSettings
from company_agent.crm_adapter.zoho_client import (
    ZohoClient,
    ZohoTokenManager,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICES_PATH = REPO_ROOT / "facts" / "prices.yaml"

# What a patient may be quoted, and how the two families are described. The
# distinction is who delivers the consultation — supplied by calidad@ 2026-08-11
# and recorded in cerebro/facts.md.
QUOTABLE_FAMILIES = {
    "PLAN INMUNONUTRICIÓN": "con nuestros especialistas",
    "PLAN NUTRICIÓN": "con nuestro equipo de nutricionistas",
}

FF_MARKER = "F&F"


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    import os

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_products(client: ZohoClient) -> list[dict]:
    """Every active product. COQL caps a page at 200, so this pages explicitly."""
    rows: list[dict] = []
    offset = 0
    page_size = 200
    while True:
        page = client.coql(
            "select id, Product_Name, Unit_Price, Product_Code, Product_Active "
            "from Products where Product_Active = true "
            f"order by Product_Name limit {coql.limit(page_size, maximum=page_size)} offset {offset}"
        )
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _consultations(name: str) -> int | None:
    """The consultation count in 'PLAN NUTRICIÓN 3 CONSULTAS'."""
    for token, following in zip(name.split(), name.split()[1:], strict=False):
        if following.upper().startswith("CONSULTA") and token.isdigit():
            return int(token)
    return None


def build_catalogue(rows: list[dict]) -> dict:
    products: dict[str, dict] = {}
    for row in rows:
        name = (row.get("Product_Name") or "").strip()
        family = next((f for f in QUOTABLE_FAMILIES if name.upper().startswith(f)), None)
        products[str(row["id"])] = {
            "name": name,
            "price_usd": row.get("Unit_Price"),
            "product_code": row.get("Product_Code"),
            "family": family,
            "friends_and_family": FF_MARKER in name.upper(),
            "consultations": _consultations(name),
            # Only non-F&F rows in a quotable family may reach a patient.
            "quotable": bool(family) and FF_MARKER not in name.upper(),
        }
    return products


def hygiene_report(products: dict) -> dict:
    """Null and duplicated Product_Codes, for calidad@ — not used as a key here."""
    null_codes = sorted(p["name"] for p in products.values() if not p["product_code"])

    by_code: dict[str, list[dict]] = {}
    for product in products.values():
        if product["product_code"]:
            by_code.setdefault(product["product_code"], []).append(product)

    duplicates = {
        code: sorted(
            ({"name": p["name"], "price_usd": p["price_usd"]} for p in group),
            key=lambda p: str(p["name"]),
        )
        for code, group in by_code.items()
        if len(group) > 1
    }
    return {
        "active_products": len(products),
        "null_product_code": {"count": len(null_codes), "names": null_codes},
        "duplicate_product_code": {"count": len(duplicates), "codes": duplicates},
    }


def render(products: dict) -> str:
    """
    Byte-stable YAML for unchanged input: sorted keys, no timestamp.

    A generated file that changes on every run cannot be diffed, and a diff is
    the only way anyone will notice a price moved.
    """
    document = {
        "families": QUOTABLE_FAMILIES,
        "products": dict(sorted(products.items())),
        "hygiene": hygiene_report(products),
    }
    header = (
        "# GENERATED by scripts/pull_products.py — do not edit by hand.\n"
        "# Source of truth: Zoho Products where Product_Active = true.\n"
        "# Keyed on the Zoho record id: Product_Code is null on ~60% of rows and\n"
        "# repeats across active rows at different prices.\n"
        "# Only `quotable: true` rows may be quoted to a patient (F&F excluded).\n"
    )
    return header + yaml.safe_dump(document, allow_unicode=True, sort_keys=True)


def _emit(rows: list[dict], *, check: bool) -> int:
    products = build_catalogue(rows)
    quotable = [p for p in products.values() if p["quotable"]]
    print(f"  [OK] {len(products)} active products, {len(quotable)} quotable")

    report = hygiene_report(products)
    if report["null_product_code"]["count"]:
        print(f"  [WARN] {report['null_product_code']['count']} products have no Product_Code")
    if report["duplicate_product_code"]["count"]:
        print(
            f"  [WARN] {report['duplicate_product_code']['count']} Product_Codes are reused "
            "across active rows — reported for calidad@, never used as a key"
        )

    rendered = render(products)
    existing = PRICES_PATH.read_text(encoding="utf-8") if PRICES_PATH.exists() else None

    if check:
        if existing == rendered:
            print("[2] facts/prices.yaml is current [OK]")
            return 0
        print("[2] facts/prices.yaml is STALE — run without --check [FAIL]")
        return 1

    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRICES_PATH.write_text(rendered, encoding="utf-8")
    state = "unchanged" if existing == rendered else "updated"
    print(f"[2] wrote {PRICES_PATH.relative_to(REPO_ROOT)} ({state})")

    for product in sorted(quotable, key=lambda p: (str(p["family"]), p["consultations"] or 0)):
        print(f"     {product['family']:24s} {product['consultations']} → ${product['price_usd']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull Zoho products into facts/prices.yaml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if facts/prices.yaml differs from Zoho",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Read the sandbox instead of production (it has no product catalogue)",
    )
    parser.add_argument(
        "--from-json",
        metavar="PATH",
        help=(
            "Render from a saved COQL response instead of calling Zoho. The service "
            "refresh token in .env carries no products scope, so this is how the "
            "catalogue gets in until that is fixed — see the module docstring."
        ),
    )
    args = parser.parse_args()

    if args.from_json:
        import json

        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        rows = payload["data"] if isinstance(payload, dict) else payload
        print(f"[1] loaded {len(rows)} products from {args.from_json}")
        return _emit(rows, check=args.check)

    _load_env()
    # CrmSettings requires the shared service key because the crm-adapter cannot
    # serve without one. This script talks to Zoho directly and never to the
    # adapter, so a placeholder keeps the settings class honest without demanding
    # a secret the task does not use.
    import os

    os.environ.setdefault("INTERNAL_API_KEY", "unused-by-pull-products")

    # Prices only exist in production — the sandbox's Products module is empty
    # and answers COQL with a 400. This is a read-only SELECT, so reading
    # production is both safe and the only way to get the real catalogue. The
    # override exists so the choice is visible rather than implied by .env.
    os.environ["ZOHO_SANDBOX"] = "true" if args.sandbox else "false"
    settings = CrmSettings()
    if not (settings.zoho_client_id and settings.zoho_refresh_token):
        print("[FAIL] Zoho credentials missing from .env")
        return 2

    client = ZohoClient(
        api_base=settings.zoho_api_base,
        tokens=ZohoTokenManager(
            accounts_url=settings.zoho_accounts_url,
            client_id=settings.zoho_client_id,
            client_secret=settings.zoho_client_secret or "",
            refresh_token=settings.zoho_refresh_token,
        ),
    )

    print(f"[1] querying Zoho ({'sandbox' if settings.zoho_sandbox else 'production'}) ...")
    rows = fetch_products(client)
    return _emit(rows, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
