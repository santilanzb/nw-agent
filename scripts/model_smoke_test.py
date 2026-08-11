"""Tiny smoke test: send 'Hola' to each model and verify a Spanish response."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from zoho_smoke_test import find_env_file, load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def main() -> int:
    env = load_dotenv(find_env_file())
    os.environ["ANTHROPIC_API_KEY"] = env.get("ANTHROPIC_API_KEY", "")
    os.environ["GOOGLE_API_KEY"] = env.get("GOOGLE_API_KEY", "")

    SYSTEM = "Eres Gutty, ejecutiva de NutriWhite. Responde en español, breve y cálido."
    USER = "Hola buenos días"

    # Anthropic
    print("[anthropic] claude-haiku-4-5 ...")
    try:
        from anthropic import Anthropic
        c = Anthropic()
        t0 = time.monotonic()
        msg = c.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            system=SYSTEM,
            messages=[{"role": "user", "content": USER}],
        )
        dt = int((time.monotonic() - t0) * 1000)
        text = "".join(b.text for b in msg.content if b.type == "text")
        print(f"  [OK] {dt}ms — {text[:200]}")
    except Exception as e:  # noqa: BLE001 - smoke test reports any failure as [FAIL]
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return 2

    # Google Gemini
    print("\n[google] gemini-3-flash ...")
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        t0 = time.monotonic()
        resp = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=USER,
            config=types.GenerateContentConfig(system_instruction=SYSTEM),
        )
        dt = int((time.monotonic() - t0) * 1000)
        print(f"  [OK] {dt}ms — {(resp.text or '')[:200]}")
    except Exception as e:  # noqa: BLE001 - smoke test reports any failure as [FAIL]
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return 3

    print("\nAll providers reachable [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
