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
    anthropic_default_model: str = "claude-haiku-4-5-20251001"
    anthropic_escalation_model: str = "claude-sonnet-4-6"
    handoff_team_group_jid: str = ""
    # Langfuse — leave empty to disable tracing
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"
    port: int = 8083
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}
