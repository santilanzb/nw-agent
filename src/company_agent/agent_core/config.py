from __future__ import annotations

from pydantic_settings import BaseSettings


class AgentCoreSettings(BaseSettings):
    database_url: str = "postgresql://agent:agent@postgres:5432/company_agent"
    rag_api_url: str = "http://rag-api:8081"
    crm_adapter_url: str = "http://crm-adapter:8082"
    waha_base_url: str = "http://waha:3000"
    waha_api_key: str = ""
    waha_hook_hmac_key: str = ""
    internal_api_key: str = ""
    anthropic_api_key: str = ""
    # Single composition tier: every patient-facing composed turn is care-class and
    # runs on the Anthropic synchronous Messages API under BAA. The two settings are
    # kept so a cheaper tier can be reintroduced for non-patient-facing work.
    anthropic_default_model: str = "claude-sonnet-5"
    anthropic_escalation_model: str = "claude-sonnet-5"
    handoff_team_group_jid: str = ""
    # Webhook signature verification is mandatory. This exists only so a local
    # docker-compose run can accept unsigned test payloads; it must never be true
    # anywhere a real WhatsApp number is attached.
    allow_unverified_webhooks: bool = False
    # Langfuse — leave empty to disable tracing
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"
    port: int = 8083
    log_level: str = "INFO"
    # Ingress durability
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    # How often the sweeper re-drives events nobody finished and resolves sends
    # left in doubt by a crash. Plain asyncio for now; this is the scheduled tick
    # that DBOS takes over once the Stage-0 spike passes.
    sweeper_interval_seconds: int = 30
    sweeper_pending_grace_seconds: int = 60

    model_config = {"env_file": ".env", "extra": "ignore"}
