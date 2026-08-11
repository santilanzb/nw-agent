from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["low", "normal", "high", "urgent"]


class HealthResponse(BaseModel):
    status: str


# ── Lookup ────────────────────────────────────────────────────────────────────

class CustomerLookupRequest(BaseModel):
    """Accepts phone (primary, WhatsApp E.164), customer_id (Zoho record id), or email."""
    phone: str | None = None        # WhatsApp number: +584145610594
    customer_id: str | None = None  # Zoho Contact record id
    email: str | None = None


class PatientProfile(BaseModel):
    """Slimmed-down Contact record safe to expose to the agent."""
    contact_id: str
    full_name: str
    email: str | None
    phone: str | None
    language: str | None                # Idioma field
    patient_status: str | None          # Estado_de_Paciente
    patient_type: str | None            # Paciente (Nuevo / Recurrente)
    community_type: str | None          # Tipo_de_Comunidad
    specialist: str | None              # Especialista.name
    consult_reason: list[str]           # Motivo_de_Consulta


# Backward-compat alias used by the OpenClaw plugin tool name "customer_lookup"
CustomerProfile = PatientProfile


# ── Deals (Tratos / Plans) ────────────────────────────────────────────────────

class CustomerOrdersRequest(BaseModel):
    customer_id: str


class DealRecord(BaseModel):
    deal_id: str
    deal_name: str
    stage: str | None
    amount: float | None
    plan_status: str | None         # Estado_del_plan
    plan_duration: str | None       # Vigencia_del_plan
    consultations_total: int | None # Consultas_del_Plan
    consultations_used: int | None  # Total_Consultas_Vistas
    exams_pending: int | None       # Ex_menes_Pendientes
    payment_method: str | None      # Formas_de_pago
    specialist: str | None


# Backward-compat alias
OrderRecord = DealRecord


# ── Consultas ─────────────────────────────────────────────────────────────────

class CustomerTicketsRequest(BaseModel):
    customer_id: str


class ConsultaRecord(BaseModel):
    consulta_id: str
    number: int | None              # N_de_Consulta
    type: str | None                # Tipo_de_consulta
    scheduled_date: str | None      # Fecha_Programada
    appointment_status: str | None  # Estado_de_la_Cita
    specialist: str | None          # Especialista
    connection_link: str | None     # Link_de_Conexi_n


# Backward-compat alias — "tickets" maps to consultas in NW context
TicketRecord = ConsultaRecord


# ── Examenes ──────────────────────────────────────────────────────────────────

class ExamenRecord(BaseModel):
    examen_id: str
    exam_name: str | None           # Nombre_del_examen.name
    process_status: str | None      # Estatus_del_Proceso
    kit_sent_date: str | None       # Fecha_Env_o_Kit
    results_received_date: str | None  # Fecha_Resultados_Recibidos
    admin_status: str | None        # Estado_Administrativo


# ── Ticket Draft (reused as handoff note) ─────────────────────────────────────

class TicketDraftRequest(BaseModel):
    customer_id: str
    summary: str = Field(min_length=5, max_length=240)
    details: str = Field(min_length=10, max_length=4000)
    priority: Priority = "normal"


class TicketDraftResponse(BaseModel):
    draft_id: str
    customer_id: str
    summary: str
    details: str
    priority: Priority
    status: str


# ── Handoff ───────────────────────────────────────────────────────────────────

class HandoffRequest(BaseModel):
    conversation_id: str | None = None
    reason: str = Field(min_length=10, max_length=2000)
    priority: Priority = "high"
    customer_id: str | None = None      # Zoho Contact record id

    # Richer context so the team notification + state row are useful
    contact_phone: str | None = None    # E.164, e.g. +584145610594
    patient_name: str | None = None
    last_message: str | None = None     # the patient's last message at handoff time


class HandoffResponse(BaseModel):
    handoff_id: str                     # handoff_state.id (uuid)
    contact_id: str | None              # Zoho Contact id (if known)
    note_id: str | None                 # Zoho Note id if created
    status: str                         # pending | claimed | resumed | expired
    message: str                        # patient-facing line
    expires_at: str | None = None       # ISO timestamp


# ── Handoff state inspection / control ────────────────────────────────────────

class HandoffStateCheckRequest(BaseModel):
    contact_phone: str                  # E.164


class HandoffStateRecordModel(BaseModel):
    """What the agent / team tools see when inspecting state."""
    active: bool
    handoff_id: str | None = None
    contact_phone: str
    contact_id: str | None = None
    patient_name: str | None = None
    status: str | None = None           # pending | claimed | None
    reason: str | None = None
    priority: str | None = None
    last_message: str | None = None
    claimed_by_phone: str | None = None
    claimed_by_name: str | None = None
    created_at: str | None = None
    claimed_at: str | None = None
    expires_at: str | None = None


class HandoffClaimRequest(BaseModel):
    contact_phone: str                  # patient's E.164
    claimer_phone: str                  # logistics member's E.164
    claimer_name: str = Field(min_length=1, max_length=80)


class HandoffClaimResponse(BaseModel):
    success: bool                       # True if this caller won the race
    reason: str                         # "claimed" | "already_claimed" | "not_found"
    state: HandoffStateRecordModel


class HandoffResumeRequest(BaseModel):
    contact_phone: str


class HandoffResumeResponse(BaseModel):
    success: bool
    reason: str                         # "resumed" | "not_found"
    state: HandoffStateRecordModel
