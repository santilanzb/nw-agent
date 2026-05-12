# Model Evaluation Harness

Side-by-side evaluation of LLMs against NutriWhite-specific prompts derived from real WhatsApp conversations and the FAQ.

## Goal

Validate the model choice (default: Claude Haiku 4.5) against alternatives (Gemini 3 Flash, GPT-5 Mini) on the criteria that matter for this use case:

1. **Spanish naturalness** — does it sound like Gutty, not a translator?
2. **Persona match** — warm, empathetic, uses correct emojis/style?
3. **Handoff trigger** — does it correctly escalate when policy says it must?
4. **Hallucination** — does it invent prices, names, availability?
5. **Tool-call correctness** — when applicable, does it pick the right tool with right args?

## Layout

```
eval/
├── README.md            # this file
├── seeds.yaml           # eval cases — input + expected behavior
├── system_prompt.md     # the canonical NutriWhite system prompt
├── run_eval.py          # runs each case against each model, saves outputs
└── results/             # generated outputs (gitignored)
```

## How to run

```bash
# Install eval deps
pip install -e ".[eval]"

# Set keys for the providers you want to test
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...

# Run all models against all cases
python -m eval.run_eval --models haiku-4.5,gemini-3-flash,gpt-5-mini

# Or just one
python -m eval.run_eval --models haiku-4.5
```

Outputs land in `eval/results/<timestamp>/<model>.jsonl`.

## Scoring

Currently **outputs only** — manual scoring against the rubric (you read each output and grade it 1–5 on each axis).

Phase 2 (later): LLM-judge using Claude Sonnet 4.6 to grade each output automatically.
