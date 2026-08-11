"""
The two policy surfaces must answer identically.

`DIRECT_FAQ_REPLIES` exists twice: once in Python for agent-core, once in
JavaScript for the OpenClaw plugin that still serves the production number.
Nothing kept them in sync, and they had already drifted — the plugin's Spanish
handoff phrase lost its accents while the Python one kept them, and both quoted
a $229 plan that Zoho had marked inactive.

This test is the interim guard. It retires when the price generator (graft G2)
renders both surfaces from `facts/prices.yaml`, at which point equality is
structural rather than asserted.
"""
from __future__ import annotations

import codecs
import re
from pathlib import Path

import pytest

from company_agent.agent_core.tasks.customer_service import DIRECT_FAQ_REPLIES

PLUGIN = Path(__file__).resolve().parents[1] / "openclaw" / "plugins" / "customer-service-tools" / "index.js"

# A JS string literal: "..." with backslash escapes. Entries are one or more of
# those joined by `+` across lines.
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_ENTRY = re.compile(r'^  (\w+):\s*\n?((?:\s*"(?:[^"\\]|\\.)*"\s*\+?\s*\n?)+),\s*$', re.MULTILINE)


def _js_direct_faq_replies() -> dict[str, str]:
    source = PLUGIN.read_text(encoding="utf-8")
    block = re.search(r"const DIRECT_FAQ_REPLIES = \{\n(.*?)\n\};", source, re.DOTALL)
    assert block, "DIRECT_FAQ_REPLIES not found in the plugin"

    replies: dict[str, str] = {}
    for key, body in _ENTRY.findall(block.group(1)):
        joined = "".join(_STRING.findall(body))
        # The literals carry \n escapes; nothing else needs decoding.
        replies[key] = codecs.decode(joined, "unicode_escape").encode("latin-1").decode("utf-8")
    return replies


def test_the_plugin_defines_the_same_faq_keys() -> None:
    assert set(_js_direct_faq_replies()) == set(DIRECT_FAQ_REPLIES)


@pytest.mark.parametrize("key", sorted(DIRECT_FAQ_REPLIES))
def test_both_surfaces_give_the_same_answer(key: str) -> None:
    assert _js_direct_faq_replies()[key] == DIRECT_FAQ_REPLIES[key]


def test_no_surface_quotes_a_discontinued_price() -> None:
    """
    `PLAN-1CONS-FULL-01` "$229" is Product_Active=false in Zoho, verified live
    2026-08-11. It was still being quoted to every patient who asked for prices.
    """
    retired = "$229"
    for key, text in DIRECT_FAQ_REPLIES.items():
        assert retired not in text, f"agent-core {key} still quotes {retired}"
    for key, text in _js_direct_faq_replies().items():
        assert retired not in text, f"openclaw plugin {key} still quotes {retired}"
