"""
Zoho CRM v8 client with automatic OAuth token refresh.

Handles:
- Access token lifecycle (refresh on 401 or expiry)
- COQL queries for reads
- REST writes (Notes for handoff)
- Phone normalization for WhatsApp number matching
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import httpx

from . import coql

# ── Phone normalization ────────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    """Strip everything except digits. E.g. '+58 414-5610594' → '584145610594'."""
    return re.sub(r"[^\d]", "", raw)


def phone_search_suffix(e164: str, suffix_len: int = 9) -> str:
    """
    Extract the last N digits of a normalized phone for a LIKE search.
    Avoids format mismatch between WhatsApp E.164 and Zoho stored format.
    """
    digits = normalize_phone(e164)
    return digits[-suffix_len:] if len(digits) >= suffix_len else digits


# ── Token manager ─────────────────────────────────────────────────────────────

class ZohoTokenManager:
    """Thread-safe access token cache with automatic refresh."""

    _EXPIRY_BUFFER_SECONDS = 120  # refresh 2 min before expiry

    def __init__(self, accounts_url: str, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._accounts_url = accounts_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            return self._refresh()

    def invalidate(self) -> str:
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0
            return self._refresh()

    def _refresh(self) -> str:
        resp = httpx.post(
            f"{self._accounts_url}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()

        if "error" in payload:
            raise RuntimeError(f"Zoho token refresh failed: {payload['error']}")

        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._expires_at = time.monotonic() + expires_in - self._EXPIRY_BUFFER_SECONDS
        return self._access_token


# ── Zoho CRM client ───────────────────────────────────────────────────────────

class ZohoClient:
    """
    Thin HTTP wrapper over Zoho CRM v8.
    Retries once on 401 with a fresh token.
    """

    def __init__(self, api_base: str, tokens: ZohoTokenManager) -> None:
        self._base = api_base.rstrip("/")
        self._tokens = tokens

    # ── Low-level ────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Zoho-oauthtoken {self._tokens.get_token()}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: dict) -> dict:
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self._base}/{path.lstrip('/')}"
        resp = httpx.request(method, url, headers=self._headers(), timeout=20, **kwargs)

        if resp.status_code == 401:
            # Token expired mid-flight — refresh once and retry
            new_headers = {"Authorization": f"Zoho-oauthtoken {self._tokens.invalidate()}"}
            resp = httpx.request(method, url, headers=new_headers, timeout=20, **kwargs)

        resp.raise_for_status()
        return resp.json()

    # ── COQL ─────────────────────────────────────────────────────────────────

    def coql(self, query: str) -> list[dict]:
        """Execute a COQL SELECT query. Returns list of record dicts."""
        result = self._post("coql", {"select_query": query})
        return result.get("data", [])

    # ── Contacts ─────────────────────────────────────────────────────────────

    CONTACT_FIELDS = (
        "id, First_Name, Last_Name, Email, Phone, Idioma, "
        "Estado_de_Paciente, Paciente, Tipo_de_Comunidad, "
        "Especialista, Motivo_de_Consulta"
    )

    def find_contact_by_phone(self, e164: str) -> dict | None:
        # Normalize first, then take the suffix: slicing the raw string would cut
        # through punctuation and yield a different (shorter) match on a formatted
        # number like "+58 414-5610594".
        pattern = coql.like_contains(phone_search_suffix(e164), digits_only=True)
        rows = self.coql(
            f"SELECT {self.CONTACT_FIELDS} FROM Contacts "
            f"WHERE Phone like {pattern} LIMIT 3"
        )
        if not rows:
            return None
        # If multiple hits, prefer exact normalized match
        norm_input = normalize_phone(e164)
        for row in rows:
            if normalize_phone(row.get("Phone") or "") == norm_input:
                return row
        return rows[0]

    def find_contact_by_id(self, contact_id: str) -> dict | None:
        rows = self.coql(
            f"SELECT {self.CONTACT_FIELDS} FROM Contacts "
            f"WHERE id = {coql.record_id(contact_id)} LIMIT 1"
        )
        return rows[0] if rows else None

    def find_contact_by_email(self, email: str) -> dict | None:
        rows = self.coql(
            f"SELECT {self.CONTACT_FIELDS} FROM Contacts "
            f"WHERE Email = {coql.quote(email)} LIMIT 1"
        )
        return rows[0] if rows else None

    # ── Leads (labelled "Contactos" in the UI) ────────────────────────────────

    # Leads do NOT use the standard Phone/Mobile fields — both are empty across
    # the whole module. The number lives in this custom field, verified live
    # 2026-08-11. Values are inconsistently formatted ("+58 4241568769",
    # "+584123138118", "6692771132"), which is why the match is a digit suffix.
    LEAD_PHONE_FIELD = "Tel_fono_con_c_digo_de_pa_s1"

    LEAD_FIELDS = (
        "id, First_Name, Last_Name, Email, Country, Especialista, "
        f"{LEAD_PHONE_FIELD}"
    )

    def find_lead_by_phone(self, e164: str) -> dict | None:
        """
        Find a not-yet-converted lead by phone.

        COQL's default universe excludes converted leads, which is what we want:
        a converted lead has a Contact record, and that is the better match.
        """
        pattern = coql.like_contains(phone_search_suffix(e164), digits_only=True)
        rows = self.coql(
            f"SELECT {self.LEAD_FIELDS} FROM Leads "
            f"WHERE {self.LEAD_PHONE_FIELD} like {pattern} LIMIT 3"
        )
        if not rows:
            return None
        norm_input = normalize_phone(e164)
        for row in rows:
            if normalize_phone(row.get(self.LEAD_PHONE_FIELD) or "") == norm_input:
                return row
        return rows[0]

    def find_by_phone(self, e164: str) -> tuple[str, dict] | None:
        """
        Resolve a WhatsApp number across both populations.

        Patients first: a Contact ("Comunidad NW") carries plan, specialist and
        consultation history, so it is the stronger match. Only if there is no
        patient do we look for a lead ("Contactos"). Searching Contacts alone —
        which is all this client used to do — meant an inbound lead, i.e. most
        new WhatsApp traffic, was never recognised at all.

        Returns (module_api_name, row).
        """
        row = self.find_contact_by_phone(e164)
        if row:
            return "Contacts", row
        row = self.find_lead_by_phone(e164)
        if row:
            return "Leads", row
        return None

    # ── Deals (Tratos) ────────────────────────────────────────────────────────

    DEAL_FIELDS = (
        "id, Deal_Name, Stage, Amount, Estado_del_plan, Vigencia_del_plan, "
        "Consultas_del_Plan, Total_Consultas_Vistas, Ex_menes_Pendientes, "
        "Formas_de_pago, Especialista"
    )

    def list_deals_for_contact(self, contact_id: str, limit: int = 5) -> list[dict]:
        return self.coql(
            f"SELECT {self.DEAL_FIELDS} FROM Deals "
            f"WHERE Contact_Name = {coql.record_id(contact_id)} "
            f"ORDER BY Created_Time DESC LIMIT {coql.limit(limit)}"
        )

    # ── Consultas ─────────────────────────────────────────────────────────────

    CONSULTA_FIELDS = (
        "id, N_de_Consulta, Tipo_de_consulta, Fecha_Programada, "
        "Estado_de_la_Cita, Especialista, Link_de_Conexi_n"
    )

    def list_consultas_for_contact(self, contact_id: str, limit: int = 5) -> list[dict]:
        return self.coql(
            f"SELECT {self.CONSULTA_FIELDS} FROM Consultas "
            f"WHERE Comunidad_NW = {coql.record_id(contact_id)} "
            f"ORDER BY Fecha_Programada DESC LIMIT {coql.limit(limit)}"
        )

    # ── Examenes ─────────────────────────────────────────────────────────────

    EXAMEN_FIELDS = (
        "id, Nombre_del_examen, Estatus_del_Proceso, "
        "Fecha_Env_o_Kit, Fecha_Resultados_Recibidos, Estado_Administrativo"
    )

    def list_examenes_for_contact(self, contact_id: str, limit: int = 10) -> list[dict]:
        return self.coql(
            f"SELECT {self.EXAMEN_FIELDS} FROM Examenes "
            f"WHERE Comunidad_NW = {coql.record_id(contact_id)} "
            f"ORDER BY Created_Time DESC LIMIT {coql.limit(limit)}"
        )

    # ── Notes (Handoff) ───────────────────────────────────────────────────────

    #: Modules a Note may be attached to. Identifiers cannot be quoted, so an
    #: allowlist is the only safe form.
    NOTE_PARENT_MODULES = frozenset({"Contacts", "Leads"})

    def create_note(
        self, parent_id: str, title: str, content: str, module: str = "Contacts"
    ) -> dict:
        """
        Add a Note to a Contact or a Lead.

        This is the handoff signal — a human asesora sees it in the CRM. The
        parent module must match where the record actually lives: a Note stamped
        `$se_module: Contacts` cannot attach to a Lead.
        """
        payload = {
            "data": [
                {
                    "Note_Title": title,
                    "Note_Content": content,
                    "Parent_Id": {"id": coql.record_id(parent_id).strip("'")},
                    "$se_module": coql.identifier(module, self.NOTE_PARENT_MODULES),
                }
            ]
        }
        return self._post("Notes", payload)

    def create_note_on_contact(self, contact_id: str, title: str, content: str) -> dict:
        """Back-compat wrapper: a Note on a patient record."""
        return self.create_note(contact_id, title, content, module="Contacts")
