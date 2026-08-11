"""
Phone is the identity key, and it must resolve across both CRM populations.

WhatsApp hands us the number on every inbound message, so it is the one
identifier we never have to ask for — email is awkward to request mid-conversation
and is a last resort.

Two live facts drive this (verified 2026-08-11, recorded in cerebro/facts.md):

  * The module labels are inverted: api `Contacts` is labelled "Comunidad NW"
    (patients), api `Leads` is labelled "Contactos".
  * Leads do not use the standard Phone/Mobile fields — both are empty across the
    whole module. Their number lives in `Tel_fono_con_c_digo_de_pa_s1`.

So searching only `Contacts.Phone`, which is what the client used to do, missed
every inbound lead: no name, no history, and a handoff with no CRM record.
"""
from __future__ import annotations

import pytest

from company_agent.crm_adapter.adapters import ZohoCrmAdapter
from company_agent.crm_adapter.coql import CoqlValueError
from company_agent.crm_adapter.zoho_client import ZohoClient

LEAD_PHONE = ZohoClient.LEAD_PHONE_FIELD


class _FakeCrm(ZohoClient):
    """Answers COQL from canned rows and records every query."""

    def __init__(self, contacts: list[dict] | None = None, leads: list[dict] | None = None):
        self.queries: list[str] = []
        self.notes: list[dict] = []
        self._contacts = contacts or []
        self._leads = leads or []

    def coql(self, query: str) -> list[dict]:  # type: ignore[override]
        self.queries.append(query)
        if "FROM Leads" in query:
            return self._leads
        return self._contacts

    def _post(self, path: str, json: dict) -> dict:  # type: ignore[override]
        self.notes.append(json)
        return {"data": [{"details": {"id": "note_1"}, "status": "success"}]}


# ── find_by_phone ─────────────────────────────────────────────────────────────

def test_a_patient_is_preferred_over_a_lead() -> None:
    crm = _FakeCrm(
        contacts=[{"id": "1", "Phone": "+584145610594", "Last_Name": "Paciente"}],
        leads=[{"id": "2", LEAD_PHONE: "+584145610594", "Last_Name": "Lead"}],
    )
    module, row = crm.find_by_phone("+584145610594")

    assert module == "Contacts"
    assert row["id"] == "1"
    # Contacts answered, so Leads was never queried.
    assert not any("FROM Leads" in q for q in crm.queries)


def test_a_lead_is_found_when_there_is_no_patient() -> None:
    """The regression: this returned nothing at all, for most inbound traffic."""
    crm = _FakeCrm(
        contacts=[],
        leads=[{"id": "2", LEAD_PHONE: "+584145610594", "Last_Name": "Lead"}],
    )
    module, row = crm.find_by_phone("+584145610594")

    assert module == "Leads"
    assert row["id"] == "2"


def test_the_lead_query_uses_the_custom_phone_field() -> None:
    """Standard Phone/Mobile are empty on every lead; querying them finds nobody."""
    crm = _FakeCrm(contacts=[], leads=[])
    crm.find_by_phone("+584145610594")

    lead_query = next(q for q in crm.queries if "FROM Leads" in q)
    assert LEAD_PHONE in lead_query
    assert "'%145610594%'" in lead_query


def test_unknown_number_resolves_to_nothing() -> None:
    assert _FakeCrm(contacts=[], leads=[]).find_by_phone("+584145610594") is None


def test_inconsistent_stored_formats_still_match_on_the_digit_suffix() -> None:
    """Live data holds '+58 4241568769', '+584123138118' and '6692771132'."""
    for stored in ("+58 4241568769", "+584241568769", "4241568769"):
        crm = _FakeCrm(contacts=[], leads=[{"id": "2", LEAD_PHONE: stored}])
        assert crm.find_by_phone("+584241568769") is not None


# ── Profile mapping ───────────────────────────────────────────────────────────

def test_lead_profile_is_marked_as_not_a_patient() -> None:
    crm = _FakeCrm(
        contacts=[],
        leads=[{"id": "2", "First_Name": "Ana", "Last_Name": "Pérez",
                "Email": "ana@example.com", LEAD_PHONE: "+584145610594"}],
    )
    profile = ZohoCrmAdapter(crm).lookup_customer("+584145610594", None, None)

    assert profile is not None
    assert profile.source_module == "Leads"
    assert profile.is_patient is False
    assert profile.full_name == "Ana Pérez"
    assert profile.phone == "+584145610594"
    # Patient-only fields are absent rather than misleadingly blank.
    assert profile.patient_status is None
    assert profile.consult_reason == []


def test_contact_profile_is_marked_as_a_patient() -> None:
    crm = _FakeCrm(
        contacts=[{"id": "1", "First_Name": "Luis", "Last_Name": "Gómez",
                   "Phone": "+584145610594", "Estado_de_Paciente": "Activo"}],
    )
    profile = ZohoCrmAdapter(crm).lookup_customer("+584145610594", None, None)

    assert profile is not None
    assert profile.source_module == "Contacts"
    assert profile.is_patient is True
    assert profile.patient_status == "Activo"


# ── Notes must target the module the record lives in ─────────────────────────

def test_a_note_can_be_attached_to_a_lead() -> None:
    crm = _FakeCrm()
    crm.create_note("4806334000169726001", "t", "c", module="Leads")

    assert crm.notes[0]["data"][0]["$se_module"] == "Leads"
    assert crm.notes[0]["data"][0]["Parent_Id"] == {"id": "4806334000169726001"}


def test_note_module_must_be_allowlisted() -> None:
    crm = _FakeCrm()
    with pytest.raises(CoqlValueError):
        crm.create_note("4806334000169726001", "t", "c", module="Deals")
    assert crm.notes == []


def test_note_parent_id_must_look_like_a_zoho_id() -> None:
    crm = _FakeCrm()
    with pytest.raises(CoqlValueError):
        crm.create_note("not-an-id", "t", "c")
    assert crm.notes == []
