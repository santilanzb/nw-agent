"""
NutriWhite agent evaluation harness.

Two modes:
  generation (default): side-by-side model eval for Spanish response quality.
    Loads cases from seeds.yaml, calls each model, writes JSONL results.
  intent: classifier correctness eval. Loads cases from intent_eval.yaml,
    hits POST /v1/classify_intent for each, checks expected_intent.
    Requires a running rag-api (RAG_API_URL + INTERNAL_API_KEY in env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"

# Force UTF-8 stdout for Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def _load_env_file() -> None:
    """
    Load .env into os.environ.
    Overwrites empty/unset values; preserves explicitly-set non-empty ones.
    """
    candidates = [
        Path(os.environ.get("NW_AGENT_ENV") or ""),
        Path(r"C:\Users\LANZ\nw-agent\.env"),
        Path(".env"),
        EVAL_DIR.parent.parent.parent.parent / ".env",
    ]
    for path in candidates:
        if path and path.is_file():
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                # Only set if currently missing OR empty (so explicit
                # non-empty system env always wins).
                if not os.environ.get(k):
                    os.environ[k] = v
            return


_load_env_file()


@dataclass(slots=True)
class EvalCase:
    id: str
    category: str
    sender_phone: str
    input: str
    expected: list[dict[str, Any]]


@dataclass(slots=True)
class IntentCase:
    id: str
    category: str
    expected_intent: str
    expected_tool: str | None
    sender_phone: str
    input: str
    expected: list[dict[str, Any]]


@dataclass(slots=True)
class ModelOutput:
    model: str
    case_id: str
    response: str
    latency_ms: int
    error: str | None = None


def load_cases() -> list[EvalCase]:
    raw = yaml.safe_load((EVAL_DIR / "seeds.yaml").read_text(encoding="utf-8"))
    return [EvalCase(**case) for case in raw["cases"]]


def load_intent_cases() -> list[IntentCase]:
    """
    Intent cases ship inside the function package that owns the intents, so a
    package cannot be installed without its evals. Cases from every installed
    package are concatenated.
    """
    from company_agent.packages.registry import discover_manifests

    cases: list[IntentCase] = []
    for package in discover_manifests():
        if package.manifest.evals is None:
            continue
        evals_dir = files("company_agent.packages") / package.name / package.manifest.evals
        for entry in sorted(evals_dir.iterdir(), key=lambda e: e.name):
            if not entry.name.endswith(".yaml"):
                continue
            raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
            cases.extend(IntentCase(**case) for case in raw.get("cases") or [])
    return cases


def load_system_prompt() -> str:
    return (EVAL_DIR / "system_prompt.md").read_text(encoding="utf-8")


def build_user_prompt(case: EvalCase) -> str:
    return (
        f"[sender_phone: {case.sender_phone}]\n"
        f"[message]:\n{case.input}"
    )


# === Model adapters ============================================================
# Each adapter: (system, user) -> response text. No tool calls in v1; we only
# evaluate raw response quality and whether the model says it would hand off.


def call_anthropic(model: str, system: str, user: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def call_openai(model: str, system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""


def call_gemini(model: str, system: str, user: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return response.text or ""


MODEL_REGISTRY = {
    "haiku-4.5": ("anthropic", "claude-haiku-4-5-20251001"),
    "sonnet-4.6": ("anthropic", "claude-sonnet-4-6"),
    "gpt-5-mini": ("openai", "gpt-5-mini"),
    "gpt-5-nano": ("openai", "gpt-5-nano"),
    "gemini-3-flash": ("google", "gemini-3-flash-preview"),
    "gemini-3-flash-lite": ("google", "gemini-3-1-flash-lite"),
}


def call_model(model_alias: str, system: str, user: str) -> str:
    if model_alias not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model alias: {model_alias}")
    provider, model_id = MODEL_REGISTRY[model_alias]

    if provider == "anthropic":
        return call_anthropic(model_id, system, user)
    if provider == "openai":
        return call_openai(model_id, system, user)
    if provider == "google":
        return call_gemini(model_id, system, user)
    raise ValueError(f"Unknown provider: {provider}")


# === Runner ===================================================================


def run_one(model_alias: str, case: EvalCase, system: str) -> ModelOutput:
    user = build_user_prompt(case)
    start = time.monotonic()
    try:
        text = call_model(model_alias, system, user)
        return ModelOutput(
            model=model_alias,
            case_id=case.id,
            response=text,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — eval harness records errors
        return ModelOutput(
            model=model_alias,
            case_id=case.id,
            response="",
            latency_ms=int((time.monotonic() - start) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )


def run(models: list[str]) -> Path:
    cases = load_cases()
    system = load_system_prompt()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {"timestamp": timestamp, "models": models, "case_count": len(cases)}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for model in models:
        out_path = run_dir / f"{model}.jsonl"
        print(f"running {model} → {out_path.name}")
        with out_path.open("w", encoding="utf-8") as fh:
            for case in cases:
                output = run_one(model, case, system)
                line = {
                    "case_id": output.case_id,
                    "category": case.category,
                    "input": case.input,
                    "expected": case.expected,
                    "model": output.model,
                    "response": output.response,
                    "latency_ms": output.latency_ms,
                    "error": output.error,
                }
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                marker = "ERR" if output.error else "ok"
                print(f"  {case.id:35s} [{marker}] {output.latency_ms}ms")

    print(f"\nresults: {run_dir}")
    return run_dir


# === Intent correctness pass ==================================================


def _call_classify_intent(base_url: str, api_key: str, message: str) -> dict:
    payload = json.dumps({"message": message, "language_hint": "es", "top_k": 5}).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/classify_intent",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-internal-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def run_intent_eval() -> Path:
    # Always use the loopback address — RAG_API_URL is the Docker-internal
    # hostname (http://rag-api:8081) and isn't resolvable from the host.
    rag_api_url = os.environ.get("INTENT_EVAL_RAG_URL", "http://127.0.0.1:8081")
    api_key = os.environ.get("INTERNAL_API_KEY", "")
    if not api_key:
        print("ERROR: INTERNAL_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    cases = load_intent_cases()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    out_path = run_dir / "intent_eval.jsonl"
    correct = 0
    total = 0

    # Tally per-intent-class accuracy for reporting
    class_totals: dict[str, int] = {}
    class_correct: dict[str, int] = {}

    print(f"intent eval → {out_path.name}  ({len(cases)} cases)")
    with out_path.open("w", encoding="utf-8") as fh:
        for case in cases:
            start = time.monotonic()
            error = None
            result: dict = {}
            try:
                result = _call_classify_intent(rag_api_url, api_key, case.input)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"

            latency_ms = int((time.monotonic() - start) * 1000)
            got_intent = result.get("intent", "") if not error else ""
            passed = (not error) and got_intent == case.expected_intent

            class_totals[case.expected_intent] = class_totals.get(case.expected_intent, 0) + 1
            class_correct[case.expected_intent] = class_correct.get(case.expected_intent, 0) + (1 if passed else 0)
            correct += int(passed)
            total += 1

            marker = "✓" if passed else "✗"
            print(
                f"  {marker} {case.id:45s} "
                f"want={case.expected_intent:35s} "
                f"got={got_intent or error!r:35s} "
                f"{latency_ms}ms"
            )
            line = {
                "case_id": case.id,
                "category": case.category,
                "input": case.input,
                "expected_intent": case.expected_intent,
                "expected_tool": case.expected_tool,
                "got_intent": got_intent,
                "got_confidence": result.get("confidence"),
                "got_decision": result.get("decision"),
                "passed": passed,
                "latency_ms": latency_ms,
                "error": error,
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(f"\nOverall: {correct}/{total} = {100*correct/total:.1f}%")
    print("\nPer-class accuracy:")
    for intent_class in sorted(class_totals):
        c = class_correct.get(intent_class, 0)
        t = class_totals[intent_class]
        flag = "" if c == t else " ← needs more seeds"
        print(f"  {intent_class:45s} {c}/{t}{flag}")

    print(f"\nresults: {run_dir}")
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="NutriWhite agent model evaluation")
    parser.add_argument(
        "--models",
        default="haiku-4.5,gemini-3-flash,gpt-5-mini",
        help=f"Comma-separated model aliases. Available: {', '.join(MODEL_REGISTRY)}",
    )
    parser.add_argument(
        "--mode",
        choices=["generation", "intent"],
        default="generation",
        help="generation: side-by-side model eval; intent: classify_intent correctness",
    )
    args = parser.parse_args()

    if args.mode == "intent":
        run_intent_eval()
    else:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        run(models)


if __name__ == "__main__":
    main()
