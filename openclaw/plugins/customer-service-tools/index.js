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

async function postJsonWithRetry(baseUrl, internalApiKey, path, payload, retries = 1, backoffMs = 250) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await postJson(baseUrl, internalApiKey, path, payload);
    } catch (err) {
      lastErr = err;
      if (attempt < retries) await new Promise((r) => setTimeout(r, backoffMs));
    }
  }
  throw lastErr;
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

const DIRECT_FAQ_REPLIES = {
  faq_location:
    "¡Hola! NutriWhite está en Caracas, Venezuela 📍\n\n" +
    "Nos encontramos en Alta Florida, Avenida Los Mangos, Centro Deportivo Caracas MultiSport, Piso 1.\n\n" +
    "También ofrecemos consultas 100% online, así que puedes atenderte desde donde estés. ¿Te gustaría conocer nuestros planes?",

  faq_services:
    "En NutriWhite te ofrecemos todo lo que necesitas para mejorar tu salud de forma integral 🌿\n\n" +
    "✅ Consultas de inmunonutrición y nutrición\n" +
    "✅ Exámenes especializados\n" +
    "✅ Suplementos específicos según tu caso y ubicación\n" +
    "✅ Protocolo 3R de acompañamiento\n" +
    "✅ Evaluación gratuita de salud\n" +
    "✅ Llamada informativa gratis de 15 minutos\n\n" +
    "Para suplementos fuera de Venezuela trabajamos con Fullscript y Wholescripts; en Venezuela lo coordina nuestro equipo de logística. ¿Quieres conocer nuestros planes de consulta?",

  faq_consultation_plans:
    "Tenemos tres planes diseñados para acompañarte en tu proceso 💙\n\n" +
    "*Plan 1 — $229 USD (1 mes):*\n" +
    "1 consulta de 90 min. Evaluación clínica-nutricional, plan de acción, plan de alimentación, guía del Protocolo 3R, recomendación de exámenes y suplementos.\n\n" +
    "*Plan 3 — $559 USD (3 meses):*\n" +
    "3 consultas. Todo lo anterior más acompañamiento de dos embajadoras, plan nutricional personalizado, emails semanales, 20+ recetas, 1 curso de la Academia y grupo de soporte por WhatsApp.\n\n" +
    "*Plan 5 — $789 USD (5 meses):*\n" +
    "5 consultas. Todo lo del Plan 3 más bootcamp de 10 días, todos los cursos de la Academia y acceso a webinars.\n\n" +
    "Los exámenes son recomendados dentro del plan, no están incluidos en el precio. Las cuotas son solo con TDC y tienen 3% de comisión bancaria. ¿Quieres agendar tu llamada gratuita de 15 minutos?",

  faq_payment_methods:
    "Aceptamos varias formas de pago para tu comodidad 💳\n\n" +
    "• PayPal\n• Zelle\n• Tarjeta de crédito (TDC)\n• Efectivo\n• Pago móvil (Venezuela)\n\n" +
    "Las cuotas están disponibles solo con TDC y se añade un 3% de comisión bancaria.\n\n" +
    "NutriWhite no trabaja directamente con seguros, pero podemos emitir factura para que gestiones el reembolso con tu corredor si tu seguro cubre nutrición. ¿Tienes alguna otra pregunta?",
};

export default definePluginEntry({
  id: "customer-service-tools",
  name: "Customer Service Tools",
  description: "NutriWhite tools for knowledge retrieval and Zoho-backed patient workflows.",
  register(api) {
    console.log("[customer-service-tools] register() called");
    const { ragApiUrl, crmAdapterUrl, internalApiKey } = pluginConfig(api);

    // ── Inbound claim hook: deterministic dispatch before LLM is invoked ────
    // NOTE: Use api.on() for typed plugin hooks like inbound_claim. The
    // generic api.registerHook() targets internal hooks and silently fails
    // to load plugin-hook names, which prevented this plugin from loading
    // at all in OpenClaw v2026.5.7.
    api.on("inbound_claim", async (event) => {
      // Group messages are team commands — let LLM handle
      if (event.isGroup) return { handled: false };

      const phone = event.senderId;
      if (!phone) return { handled: false };

      // ── Step 1: Active handoff mute ──────────────────────────────────────
      let handoffState;
      try {
        handoffState = await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff/state/check", {
          contact_phone: phone,
        });
      } catch {
        return { handled: false }; // fail open — LLM will check on its turn
      }
      if (handoffState.active) return { handled: true }; // silent mute

      // ── Step 2: Classify intent ──────────────────────────────────────────
      let cls;
      try {
        cls = await postJson(ragApiUrl, internalApiKey, "/v1/classify_intent", {
          message: event.content,
          language_hint: "es",
          top_k: 3,
        });
      } catch {
        return { handled: false }; // fail open
      }

      // Only deterministically handle high-confidence executes
      if (cls.decision !== "execute") return { handled: false };

      const { intent, dispatch } = cls;

      // ── Step 3a: Handoff triggers ────────────────────────────────────────
      if (dispatch?.tool === "handoff_human") {
        const handoffPayload = {
          contact_phone: phone,
          reason: dispatch.params?.reason ?? intent,
          priority: dispatch.params?.priority ?? "high",
          last_message: event.content,
          patient_name: event.senderName ?? null,
          conversation_id: event.conversationId ?? event.sessionKey ?? null,
        };
        try {
          await postJsonWithRetry(crmAdapterUrl, internalApiKey, "/v1/handoff", handoffPayload);
        } catch (err) {
          // NOTE: /v1/handoff failed after one retry — mute row not written.
          // The agent will answer on the next patient turn. The missed-reply
          // watchdog (scripts/openclaw_pending_messages.py) should catch it.
          console.error(`[nw-hook] /v1/handoff failed (phone=${phone}): ${err.message}`);
        }

        const phrase =
          intent === "handoff_english"
            ? "Let me connect you with a colleague who'll attend you in English 🩵"
            : "Para esto te conecto con una asesora que te dara la mejor recomendacion segun tu caso 🩵 Un momento por favor.";

        return { handled: true, reply: { text: phrase } };
      }

      // ── Step 3b: Direct FAQ ──────────────────────────────────────────────
      const faqText = DIRECT_FAQ_REPLIES[intent];
      if (faqText) return { handled: true, reply: { text: faqText } };

      // ── Step 3c: Acknowledgment — silent end of turn ─────────────────────
      if (intent === "acknowledgment") return { handled: true };

      // ── Step 3d: Everything else — LLM composes ─────────────────────────
      return { handled: false };
    });

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
          return faqAnswer("ubicacion", DIRECT_FAQ_REPLIES.faq_location, "knowledge/raw/01_company_overview.md");
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
          return faqAnswer("servicios", DIRECT_FAQ_REPLIES.faq_services, "knowledge/raw/01_company_overview.md; knowledge/raw/04_supplements.md");
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
          return faqAnswer("planes_consulta", DIRECT_FAQ_REPLIES.faq_consultation_plans, "knowledge/raw/02_consultation_plans.md");
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
          return faqAnswer("pagos", DIRECT_FAQ_REPLIES.faq_payment_methods, "knowledge/raw/02_consultation_plans.md; knowledge/raw/06_faq.md");
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
