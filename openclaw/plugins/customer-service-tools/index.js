import { Type } from "@sinclair/typebox";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const DEFAULT_RAG_API_URL = "http://127.0.0.1:8081";
const DEFAULT_CRM_ADAPTER_URL = "http://127.0.0.1:8082";
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

function localHttpBaseUrl(value, fieldName) {
  const url = new URL(value);
  if (url.protocol !== "http:" || !LOOPBACK_HOSTS.has(url.hostname)) {
    throw new Error(`${fieldName} must be a loopback http URL.`);
  }
  return url.origin;
}

function pluginConfig(api) {
  const config = api.pluginConfig ?? {};
  return {
    ragApiUrl: localHttpBaseUrl(config.ragApiUrl ?? DEFAULT_RAG_API_URL, "ragApiUrl"),
    crmAdapterUrl: localHttpBaseUrl(config.crmAdapterUrl ?? DEFAULT_CRM_ADAPTER_URL, "crmAdapterUrl"),
    internalApiKey: config.internalApiKey ?? "",
  };
}

async function postJson(baseUrl, internalApiKey, path, payload) {
  if (!internalApiKey) {
    throw new Error("internalApiKey is not set for the customer-service-tools plugin.");
  }

  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-internal-api-key": internalApiKey,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Request failed (${response.status}): ${body}`);
  }

  return response.json();
}

function asText(value) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(value, null, 2),
      },
    ],
  };
}

function faqAnswer(topic, answer, sourceUri) {
  return asText({
    topic,
    source_uri: sourceUri,
    answer,
    instruction:
      "Responde en español usando solo este contenido. No digas que vas a buscar. No escales si la pregunta coincide con este tema.",
  });
}

export default definePluginEntry({
  id: "customer-service-tools",
  name: "Customer Service Tools",
  description: "NutriWhite tools for knowledge retrieval and Zoho-backed patient workflows.",
  register(api) {
    const { ragApiUrl, crmAdapterUrl, internalApiKey } = pluginConfig(api);

    // ── Intent classifier (call FIRST after check_handoff_state) ────────────
    api.registerTool(
      {
        name: "classify_intent",
        description:
          "OBLIGATORIA después de check_handoff_state y antes de cualquier otra acción. " +
          "Clasifica el mensaje del paciente para decidir qué hacer. Devuelve un objeto con " +
          "{intent, confidence, decision, dispatch}. " +
          "Si decision='execute' y dispatch.tool tiene un nombre, llama EXACTAMENTE a esa tool con dispatch.params " +
          "(fusionado con los parámetros que tú conozcas del contexto, como contact_phone). " +
          "Si decision='clarify', pregunta al paciente para desambiguar (sugiere top_matches en tu pregunta). " +
          "Si decision='fallback_llm', usa tu juicio con las reglas habituales.",
        parameters: Type.Object({
          message: Type.String({ minLength: 1 }),
          language_hint: Type.Optional(Type.String()),
        }),
        async execute(_id, params) {
          const result = await postJson(ragApiUrl, internalApiKey, "/v1/classify_intent", {
            message: params.message,
            language_hint: params.language_hint ?? "es",
            top_k: 5,
          });
          return asText(result);
        },
      },
    );

    // ── Knowledge retrieval ──────────────────────────────────────────────────
    api.registerTool(
      {
        name: "kb_search",
        description:
          "OBLIGATORIA antes de responder preguntas generales de NutriWhite: ubicacion/sede, compras, productos/servicios, planes, precios, metodos de pago, cuotas, examenes, suplementos, Protocolo 3R, seguros o llamada gratis. " +
          "Usa resultados aprobados de la base de conocimiento y cita source_uri. Si no hay resultados relevantes, no improvises; escala con handoff_human.",
        parameters: Type.Object({
          query: Type.String({ minLength: 3 }),
          top_k: Type.Optional(Type.Integer({ minimum: 1, maximum: 10 })),
          corpus: Type.Optional(Type.String()),
          product: Type.Optional(Type.String()),
          language: Type.Optional(Type.String()),
        }),
        async execute(_id, params) {
          const result = await postJson(ragApiUrl, internalApiKey, "/v1/retrieve", {
            query: params.query,
            top_k: params.top_k ?? 5,
            corpus: params.corpus ?? "default",
            product: params.product ?? null,
            language: params.language ?? null,
          });
          return asText(result);
        },
      },
    );

    api.registerTool(
      {
        name: "faq_location",
        description:
          "Usa esta herramienta para responder de forma directa cuando pregunten donde esta NutriWhite, ubicacion, sede o direccion.",
        parameters: Type.Object({}),
        async execute() {
          return faqAnswer(
            "ubicacion",
            "NutriWhite esta en Caracas, Venezuela, en Alta Florida, Avenida Los Mangos, Centro Deportivo Caracas MultiSport, Piso 1. Tambien ofrecemos consultas online para pacientes desde cualquier lugar.",
            "knowledge/raw/01_company_overview.md",
          );
        },
      },
    );

    api.registerTool(
      {
        name: "faq_services",
        description:
          "Usa esta herramienta para responder que ofrece NutriWhite, que productos/servicios tiene, o que puede comprar un paciente.",
        parameters: Type.Object({}),
        async execute() {
          return faqAnswer(
            "servicios",
            "NutriWhite ofrece consultas de Inmunonutricion, consultas de nutricion, examenes especializados, suplementos especificos coordinados segun la ubicacion del paciente, evaluacion gratuita de salud, llamada gratuita de 15 minutos y acompanamiento con el Protocolo 3R. Para suplementos, fuera de Venezuela se trabaja con Fullscript y Wholescripts; en Venezuela coordina el equipo de logistica interna.",
            "knowledge/raw/01_company_overview.md; knowledge/raw/04_supplements.md",
          );
        },
      },
    );

    api.registerTool(
      {
        name: "faq_consultation_plans",
        description:
          "Usa esta herramienta para responder que planes de consulta hay disponibles, precios de planes, costo de planes, que incluye cada plan, detalles de Plan 1/Plan 3/Plan 5 o informacion comercial general de planes. No uses customer_lookup para informacion publica de planes.",
        parameters: Type.Object({}),
        async execute() {
          return faqAnswer(
            "planes_consulta",
            "Planes disponibles: Plan 1 Consulta (Basico): $229 USD, duracion 1 mes, 1 consulta de 90 minutos. Incluye evaluacion clinico/nutricional, informe con plan de accion, plan de alimentacion general, guia del Protocolo 3R, recomendacion de examenes especializados y recomendacion de suplementos. Plan 3 Consultas (Mas Recomendado): $559 USD, duracion 3 meses, 3 consultas/seguimientos. Incluye todo lo del Plan 1, mas acompanamiento de dos embajadoras, plan nutricional personalizado, emails semanales, coleccion de 20+ recetas, 1 curso de la Academia, grupo de soporte por WhatsApp, entrega de menu, material de consulta y lista de productos. Estructura: primera cita de 90 min, control 10-15 dias despues, segunda consulta de 90 min. Plan 5 Consultas (Premium): $789 USD, duracion 5 meses, 5 consultas/seguimientos. Incluye todo lo del Plan 3, mas bootcamp de 10 dias, acceso a todos los cursos de la Academia, acceso a webinars y descuentos en eventos. Los planes incluyen recomendacion de examenes; no digas que los examenes estan incluidos en el precio. No calcules cuotas ni comisiones; si preguntan por cuotas, indica que son solo con TDC y se agrega 3% de comision bancaria.",
            "knowledge/raw/02_consultation_plans.md",
          );
        },
      },
    );

    api.registerTool(
      {
        name: "faq_payment_methods",
        description:
          "Usa esta herramienta para metodos de pago, cuotas, TDC, comision, seguro o reembolso.",
        parameters: Type.Object({}),
        async execute() {
          return faqAnswer(
            "pagos",
            "Metodos de pago: PayPal, Zelle, Tarjeta de Credito (TDC), Efectivo y Pago movil en Venezuela. Las cuotas estan disponibles unicamente con TDC y se agrega 3% de comision bancaria. NutriWhite no trabaja directamente con seguros, pero puede emitir factura para que el paciente gestione reembolso con su corredor si su seguro cubre nutricion.",
            "knowledge/raw/02_consultation_plans.md; knowledge/raw/06_faq.md",
          );
        },
      },
    );

    // ── Patient lookup ───────────────────────────────────────────────────────
    api.registerTool(
      {
        name: "customer_lookup",
        description:
          "Buscar paciente por número de WhatsApp (preferido), email, o ID de Zoho. " +
          "El número debe coincidir con el remitente del mensaje.",
        parameters: Type.Object({
          phone: Type.Optional(Type.String({ description: "Formato E.164: +584145610594" })),
          email: Type.Optional(Type.String()),
          customer_id: Type.Optional(Type.String({ description: "Zoho Contact id" })),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/customer/profile", {
            phone: params.phone ?? null,
            email: params.email ?? null,
            customer_id: params.customer_id ?? null,
          });
          return asText(result);
        },
      },
    );

    // ── Deals / Plans (Tratos) ────────────────────────────────────────────────
    api.registerTool(
      {
        name: "customer_orders",
        description: "Listar planes activos del paciente (Tratos en Zoho).",
        parameters: Type.Object({
          customer_id: Type.String(),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/customer/orders", params);
          return asText(result);
        },
      },
    );

    // ── Consultas ─────────────────────────────────────────────────────────────
    api.registerTool(
      {
        name: "customer_tickets",
        description: "Listar consultas programadas y vistas del paciente.",
        parameters: Type.Object({
          customer_id: Type.String(),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/customer/tickets", params);
          return asText(result);
        },
      },
    );

    api.registerTool(
      {
        name: "customer_consultas",
        description: "Alias claro de customer_tickets — consultas del paciente.",
        parameters: Type.Object({
          customer_id: Type.String(),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/customer/consultas", params);
          return asText(result);
        },
      },
    );

    // ── Exámenes ──────────────────────────────────────────────────────────────
    api.registerTool(
      {
        name: "customer_examenes",
        description: "Listar exámenes del paciente con su estatus de proceso.",
        parameters: Type.Object({
          customer_id: Type.String(),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/customer/examenes", params);
          return asText(result);
        },
      },
    );

    // ── Note draft for human review ──────────────────────────────────────────
    api.registerTool(
      {
        name: "ticket_create_draft",
        description:
          "Crear una nota en el contacto de Zoho para revisión humana. Útil para resumir el caso antes de un handoff.",
        parameters: Type.Object({
          customer_id: Type.String(),
          summary: Type.String({ minLength: 5 }),
          details: Type.String({ minLength: 10 }),
          priority: Type.Optional(
            Type.Union([
              Type.Literal("low"),
              Type.Literal("normal"),
              Type.Literal("high"),
              Type.Literal("urgent"),
            ]),
          ),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/tickets/draft", {
            ...params,
            priority: params.priority ?? "normal",
          });
          return asText(result);
        },
      },
    );

    // ── Handoff state check (called by Gutty on EVERY patient turn) ──────────
    api.registerTool(
      {
        name: "check_handoff_state",
        description:
          "OBLIGATORIA en cada turno antes de responder al paciente. Devuelve si la conversación está en handoff humano activo. " +
          "Si la respuesta tiene active=true, NO RESPONDAS al paciente — la asesora está atendiendo. " +
          "El parámetro contact_phone debe ser el número de WhatsApp del remitente en formato E.164 (+584145610594).",
        parameters: Type.Object({
          contact_phone: Type.String({ description: "E.164, ej. +584145610594" }),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff/state/check", {
            contact_phone: params.contact_phone,
          });
          return asText(result);
        },
      },
    );

    // ── Handoff: escalate to logistics team ──────────────────────────────────
    api.registerTool(
      {
        name: "handoff_human",
        description:
          "Escalar la conversación a una asesora humana. Crea una nota en el contacto de Zoho y abre un estado de handoff (pending) " +
          "que silencia al agente para este paciente hasta que un miembro del equipo lo tome. " +
          "SIEMPRE incluye contact_phone (E.164 del remitente) y, si lo conoces, patient_name y last_message para que el equipo tenga contexto.",
        parameters: Type.Object({
          conversation_id: Type.String(),
          reason: Type.String({ minLength: 10 }),
          customer_id: Type.Optional(Type.String({ description: "Zoho Contact id si se conoce" })),
          contact_phone: Type.Optional(Type.String({ description: "E.164 del paciente, ej. +584145610594" })),
          patient_name: Type.Optional(Type.String()),
          last_message: Type.Optional(Type.String({ description: "Último mensaje del paciente" })),
          priority: Type.Optional(
            Type.Union([
              Type.Literal("low"),
              Type.Literal("normal"),
              Type.Literal("high"),
              Type.Literal("urgent"),
            ]),
          ),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff", {
            ...params,
            priority: params.priority ?? "high",
          });
          return asText(result);
        },
      },
    );

    // ── Team commands: claim / resume (used in the "Gutty Agent" group) ──────
    // Triggered when a logistics member mentions Gutty in the team group:
    //   "@Gutty tomo +584145610594"     → team_claim_handoff
    //   "@Gutty resume +584145610594"   → team_resume_handoff
    api.registerTool(
      {
        name: "team_claim_handoff",
        description:
          "Tomar un caso de handoff. Marca el handoff como 'claimed' por el miembro del equipo. " +
          "Solo invocar cuando el mensaje viene del grupo del equipo de logística ('Gutty Agent'). " +
          "Si otro miembro ya tomó el caso (success=false, reason='already_claimed'), responde en el grupo: " +
          "'Ese caso ya lo tomó {claimed_by_name}.'",
        parameters: Type.Object({
          contact_phone: Type.String({ description: "E.164 del paciente cuyo caso se toma" }),
          claimer_phone: Type.String({ description: "E.164 del miembro del equipo que toma" }),
          claimer_name: Type.String({ description: "Nombre del miembro del equipo, ej. 'María'" }),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff/claim", params);
          return asText(result);
        },
      },
    );

    api.registerTool(
      {
        name: "team_resume_handoff",
        description:
          "Cerrar un handoff. El paciente vuelve a poder hablar con Gutty. " +
          "Solo invocar desde el grupo de logística cuando un miembro del equipo lo indique explícitamente.",
        parameters: Type.Object({
          contact_phone: Type.String({ description: "E.164 del paciente cuyo caso se cierra" }),
        }),
        async execute(_id, params) {
          const result = await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff/resume", {
            contact_phone: params.contact_phone,
          });
          return asText(result);
        },
      },
    );
  },
});
