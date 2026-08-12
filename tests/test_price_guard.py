"""
The dollar guard, and the price table it checks against.

A number a patient is told is a number the business has to honour. The system
prompt already asks the model not to invent prices — and on 2026-08-11 both
policy surfaces and the retrieval corpus were all quoting a $229 plan Zoho had
marked inactive, so the model would have been *grounded* in the wrong number and
said it with confidence. Asking is not enough.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal

import pytest

from company_agent.agent_core.models import ClassificationResult, TurnContext
from company_agent.agent_core.routing.retrieval_client import RetrievedChunk
from company_agent.packages.customer_service.policy import DIRECT_FAQ_REPLIES
from company_agent.packages.customer_service.prices import (
    amounts_in,
    known_amounts,
    quotable_plans,
    unverified_amounts,
)
from company_agent.packages.customer_service.task import CustomerServiceTask

# ── Parsing amounts out of Spanish WhatsApp copy ─────────────────────────────

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cuesta $249 USD", {Decimal(249)}),
        ("$249 o $399", {Decimal(249), Decimal(399)}),
        ("249 USD", {Decimal(249)}),
        ("$1,690 el combo", {Decimal(1690)}),
        ("$49.99 el curso", {Decimal("49.99")}),
        ("sin precio alguno", set()),
        # A consultation count is not a price.
        ("3 consultas", set()),
    ],
)
def test_amounts_are_read_out_of_copy(text: str, expected: set) -> None:
    assert amounts_in(text) == expected


# ── The table ────────────────────────────────────────────────────────────────

def test_the_generated_table_has_the_two_quotable_families() -> None:
    families = {p["family"] for p in quotable_plans()}
    assert families == {"PLAN INMUNONUTRICIÓN", "PLAN NUTRICIÓN"}


def test_friends_and_family_rows_are_never_quotable() -> None:
    """An unqualified discount from a bot is a revenue leak with no audit trail."""
    assert all(not p["friends_and_family"] for p in quotable_plans())


def test_the_retired_price_is_not_in_the_table() -> None:
    assert Decimal(229) not in known_amounts()


def test_the_faq_copy_and_the_table_agree_in_both_directions() -> None:
    """
    The FAQ string is hand-written and the table is generated from Zoho. Drift
    between them is exactly how $229 survived, so it is checked rather than
    trusted — every price Gutty quotes must be a live product, and every live
    quotable plan must be offered.
    """
    quoted = amounts_in(DIRECT_FAQ_REPLIES["faq_consultation_plans"])
    catalogue = {Decimal(str(p["price_usd"])) for p in quotable_plans()}

    assert quoted - catalogue == set(), "the FAQ quotes a price that is not an active product"
    assert catalogue - quoted == set(), "an active quotable plan is missing from the FAQ"


def test_every_quoted_price_is_still_the_one_zoho_holds() -> None:
    by_family = {}
    for plan in quotable_plans():
        by_family.setdefault(plan["family"], {})[plan["consultations"]] = plan["price_usd"]

    assert by_family["PLAN INMUNONUTRICIÓN"] == {1: 249, 2: 399, 4: 599, 6: 799}
    assert by_family["PLAN NUTRICIÓN"] == {1: 149, 2: 279, 3: 329, 5: 450}


# ── The guard ────────────────────────────────────────────────────────────────

def test_a_real_price_passes() -> None:
    assert unverified_amounts("El plan de 1 consulta cuesta $249 USD") == set()


def test_an_invented_price_is_caught() -> None:
    assert unverified_amounts("Te lo dejo en $199") == {Decimal(199)}


def test_the_retired_price_is_caught() -> None:
    """The exact failure this exists for."""
    assert unverified_amounts("El Plan 1 cuesta $229 USD") == {Decimal(229)}


def test_an_amount_the_model_was_shown_is_allowed() -> None:
    """
    A patient may ask about an exam whose price lives in the corpus rather than
    the plan catalogue. Repeating what the documentation says is not inventing.
    """
    grounding = "El examen GI MAP cuesta $490 USD."
    assert unverified_amounts("El GI MAP está en $490", grounding=grounding) == set()


def test_an_amount_in_neither_is_still_caught_when_grounded() -> None:
    """
    Grounding widens what is allowed; it does not switch the guard off. $777 is
    deliberately not a product price and not in the documentation shown.
    """
    grounding = "El examen GI MAP cuesta $490 USD."
    assert Decimal(777) not in known_amounts()
    assert unverified_amounts("Te sale en $777 con descuento", grounding=grounding) == {
        Decimal(777)
    }


# ── End to end through the task ──────────────────────────────────────────────

class _InventingLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def model(self, tier: str) -> str:
        return "model"

    async def compose(self, **kwargs) -> tuple[str, int, int]:
        return self._reply, 10, 5


class _NoRetrieval:
    async def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        return []


class _NoEpisodes:
    async def recent(self, identity_id, limit: int = 6):
        return []


def _ctx() -> TurnContext:
    return TurnContext(
        turn_id=uuid.uuid4(),
        phone="+584145610594",
        contact_id=None,
        inbound_text="me haces un descuento?",
        inbound_event_id="evt-1",
        classification=ClassificationResult(
            intent="unknown", confidence=0.1, decision="fallback_llm", dispatch=None, top_matches=[]
        ),
        identity_id=uuid.uuid4(),
    )


def _run(reply: str):
    task = CustomerServiceTask(
        llm=_InventingLLM(reply), retrieval=_NoRetrieval(), episodes=_NoEpisodes()
    )
    return asyncio.run(task.handle(_ctx()))


def test_a_turn_that_invents_a_price_goes_to_a_human() -> None:
    result = _run("Claro, te lo dejo en $199 USD 🩵")

    assert result.handoff is not None
    assert result.handoff.reason == "unverified_price"
    assert result.composed_by_llm is False
    # The patient never sees the invented number.
    assert "199" not in (result.reply_text or "")


def test_a_turn_quoting_a_real_price_is_delivered() -> None:
    result = _run("El plan de 1 consulta de nutrición cuesta $149 USD 🩵")

    assert result.handoff is None
    assert result.composed_by_llm is True
    assert "149" in result.reply_text


def test_a_reply_with_no_prices_is_untouched() -> None:
    result = _run("Con gusto te acompaño en tu proceso 🩵")

    assert result.handoff is None
    assert result.composed_by_llm is True


def test_the_guard_does_not_fire_on_consultation_counts() -> None:
    """'3 consultas' is not $3, and a guard with false positives gets disabled."""
    result = _run("El plan incluye 3 consultas y 2 controles 🩵")

    assert result.handoff is None
    assert not re.search(r"\$", result.reply_text or "")
