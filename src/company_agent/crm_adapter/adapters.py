from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import uuid4

from .models import (
    ConsultaRecord,
    CustomerProfile,
    DealRecord,
    ExamenRecord,
    HandoffRequest,
    HandoffResponse,
    OrderRecord,
    TicketDraftRequest,
    TicketDraftResponse,
    TicketRecord,
)

# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseCrmAdapter(ABC):
    @abstractmethod
    def lookup_customer(
        self,
        phone: str | None,
        customer_id: str | None,
        email: str | None,
    ) -> CustomerProfile | None:
        raise NotImplementedError

    @abstractmethod
    def list_orders(self, customer_id: str) -> Sequence[OrderRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_tickets(self, customer_id: str) -> Sequence[TicketRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_examenes(self, customer_id: str) -> Sequence[ExamenRecord]:
        raise NotImplementedError

    @abstractmethod
    def create_ticket_draft(self, request: TicketDraftRequest) -> TicketDraftResponse:
        raise NotImplementedError

    @abstractmethod
    def handoff(self, request: HandoffRequest) -> HandoffResponse:
        raise NotImplementedError


# ── Mock adapter (local dev / eval without Zoho) ─────────────────────────────

class MockCrmAdapter(BaseCrmAdapter):
    def __init__(self) -> None:
        self._customers: dict[str, CustomerProfile] = {
            "cust_1001": CustomerProfile(
                contact_id="cust_1001",
                full_name="Camila Valecillos",
                email="camilavalecillos1@gmail.com",
                phone="+584145610594",
                language="Español",
                patient_status="Activo",
                patient_type="Nuevo",
                community_type="Paciente",
                specialist="Mariana White",
                consult_reason=["Digestivo"],
            ),
        }

    def lookup_customer(
        self,
        phone: str | None,
        customer_id: str | None,
        email: str | None,
    ) -> CustomerProfile | None:
        for c in self._customers.values():
            if phone and c.phone and phone.replace(" ", "") in c.phone.replace(" ", ""):
                return c
            if customer_id and c.contact_id == customer_id:
                return c
            if email and c.email and c.email.lower() == email.lower():
                return c
        return None

    def list_orders(self, customer_id: str) -> Sequence[DealRecord]:
        return [
            DealRecord(
                deal_id="deal_001",
                deal_name="Plan 3 Consultas",
                stage="Closed Won",
                amount=559.0,
                plan_status="Activo",
                plan_duration="3 meses",
                consultations_total=3,
                consultations_used=1,
                exams_pending=1,
                payment_method="Zelle",
                specialist="Mariana White",
            )
        ]

    def list_tickets(self, customer_id: str) -> Sequence[ConsultaRecord]:
        return [
            ConsultaRecord(
                consulta_id="con_001",
                number=1,
                type="Consulta Inicial",
                scheduled_date="2026-04-30",
                appointment_status="Programada",
                specialist="Mariana White",
                connection_link="https://meet.google.com/abc-defg-hij",
            )
        ]

    def list_examenes(self, customer_id: str) -> Sequence[ExamenRecord]:
        return []

    def create_ticket_draft(self, request: TicketDraftRequest) -> TicketDraftResponse:
        return TicketDraftResponse(
            draft_id=f"draft_{uuid4().hex[:10]}",
            customer_id=request.customer_id,
            summary=request.summary,
            details=request.details,
            priority=request.priority,
            status="draft_created",
        )

    def handoff(self, request: HandoffRequest) -> HandoffResponse:
        return HandoffResponse(
            handoff_id=f"handoff_{uuid4().hex[:10]}",
            contact_id=request.customer_id,
            note_id=None,
            status="queued",
            message="Handoff registrado. Una asesora te contactará pronto 🩵",
        )


# ── Zoho CRM adapter ──────────────────────────────────────────────────────────

class ZohoCrmAdapter(BaseCrmAdapter):
    """
    Live adapter against Zoho CRM v8 (sandbox or production).
    Uses COQL for reads and REST for Notes (handoff).
    """

    def __init__(self, client: ZohoClient) -> None:  # noqa: F821 — forward ref
        self._crm = client

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _str(val: object) -> str | None:
        if val is None:
            return None
        if isinstance(val, dict):
            return val.get("name") or str(val.get("id", ""))
        return str(val) if val != "" else None

    @staticmethod
    def _int(val: object) -> int | None:
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float(val: object) -> float | None:
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def _to_profile(self, row: dict) -> CustomerProfile:
        reasons = row.get("Motivo_de_Consulta") or []
        if isinstance(reasons, str):
            reasons = [r.strip() for r in reasons.split(";") if r.strip()]
        return CustomerProfile(
            contact_id=str(row["id"]),
            full_name=f"{row.get('First_Name', '')} {row.get('Last_Name', '')}".strip(),
            email=self._str(row.get("Email")),
            phone=self._str(row.get("Phone")),
            language=self._str(row.get("Idioma")),
            patient_status=self._str(row.get("Estado_de_Paciente")),
            patient_type=self._str(row.get("Paciente")),
            community_type=self._str(row.get("Tipo_de_Comunidad")),
            specialist=self._str(row.get("Especialista")),
            consult_reason=reasons,
        )

    def _to_deal(self, row: dict) -> DealRecord:
        return DealRecord(
            deal_id=str(row["id"]),
            deal_name=self._str(row.get("Deal_Name")) or "",
            stage=self._str(row.get("Stage")),
            amount=self._float(row.get("Amount")),
            plan_status=self._str(row.get("Estado_del_plan")),
            plan_duration=self._str(row.get("Vigencia_del_plan")),
            consultations_total=self._int(row.get("Consultas_del_Plan")),
            consultations_used=self._int(row.get("Total_Consultas_Vistas")),
            exams_pending=self._int(row.get("Ex_menes_Pendientes")),
            payment_method=self._str(row.get("Formas_de_pago")),
            specialist=self._str(row.get("Especialista")),
        )

    def _to_consulta(self, row: dict) -> ConsultaRecord:
        return ConsultaRecord(
            consulta_id=str(row["id"]),
            number=self._int(row.get("N_de_Consulta")),
            type=self._str(row.get("Tipo_de_consulta")),
            scheduled_date=self._str(row.get("Fecha_Programada")),
            appointment_status=self._str(row.get("Estado_de_la_Cita")),
            specialist=self._str(row.get("Especialista")),
            connection_link=self._str(row.get("Link_de_Conexi_n")),
        )

    def _to_examen(self, row: dict) -> ExamenRecord:
        return ExamenRecord(
            examen_id=str(row["id"]),
            exam_name=self._str(row.get("Nombre_del_examen")),
            process_status=self._str(row.get("Estatus_del_Proceso")),
            kit_sent_date=self._str(row.get("Fecha_Env_o_Kit")),
            results_received_date=self._str(row.get("Fecha_Resultados_Recibidos")),
            admin_status=self._str(row.get("Estado_Administrativo")),
        )

    # ── public interface ──────────────────────────────────────────────────────

    def lookup_customer(
        self,
        phone: str | None,
        customer_id: str | None,
        email: str | None,
    ) -> CustomerProfile | None:
        row: dict | None = None

        if phone:
            row = self._crm.find_contact_by_phone(phone)
        if not row and customer_id:
            row = self._crm.find_contact_by_id(customer_id)
        if not row and email:
            row = self._crm.find_contact_by_email(email)

        return self._to_profile(row) if row else None

    def list_orders(self, customer_id: str) -> Sequence[DealRecord]:
        rows = self._crm.list_deals_for_contact(customer_id)
        return [self._to_deal(r) for r in rows]

    def list_tickets(self, customer_id: str) -> Sequence[ConsultaRecord]:
        rows = self._crm.list_consultas_for_contact(customer_id)
        return [self._to_consulta(r) for r in rows]

    def list_examenes(self, customer_id: str) -> Sequence[ExamenRecord]:
        rows = self._crm.list_examenes_for_contact(customer_id)
        return [self._to_examen(r) for r in rows]

    def create_ticket_draft(self, request: TicketDraftRequest) -> TicketDraftResponse:
        # In NutriWhite context: create a Note on the Contact for human review
        title = f"[Agente IA] {request.summary}"
        self._crm.create_note_on_contact(
            contact_id=request.customer_id,
            title=title,
            content=request.details,
        )
        return TicketDraftResponse(
            draft_id=f"note_{uuid4().hex[:10]}",
            customer_id=request.customer_id,
            summary=request.summary,
            details=request.details,
            priority=request.priority,
            status="note_created_in_crm",
        )

    def handoff(self, request: HandoffRequest) -> HandoffResponse:
        note_id: str | None = None

        if request.customer_id:
            title = f"[Handoff IA] {request.reason[:80]}"
            content = (
                f"Conversación ID: {request.conversation_id or 'sin id'}\n"
                f"Prioridad: {request.priority}\n\n"
                f"Motivo:\n{request.reason}"
            )
            result = self._crm.create_note_on_contact(
                contact_id=request.customer_id,
                title=title,
                content=content,
            )
            # Zoho returns {"data": [{"details": {"id": "..."}, "status": "success"}]}
            try:
                note_id = result["data"][0]["details"]["id"]
            except (KeyError, IndexError, TypeError):
                note_id = None

        return HandoffResponse(
            handoff_id=f"handoff_{uuid4().hex[:10]}",
            contact_id=request.customer_id,
            note_id=note_id,
            status="handoff_registered",
            message="Una asesora te contactará pronto 🩵",
        )
