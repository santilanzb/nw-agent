from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "crm-adapter"
    internal_api_key: str = Field(alias="INTERNAL_API_KEY")

    # Postgres connection (used for handoff_state — Zoho stays the system of record for Notes)
    database_url: str = Field(
        default="postgresql://agent:agent@postgres:5432/company_agent",
        alias="DATABASE_URL",
    )

    # Handoff state lifecycle. Two windows, because a case nobody picks up and a
    # case that was picked up and ran long are different failures: the first is
    # the team missing a patient, the second is an asesora still working. One
    # 24h clock started at creation meant a case claimed at hour 23 expired an
    # hour later, mid-conversation.
    handoff_pending_expire_hours: int = Field(default=4, alias="HANDOFF_PENDING_EXPIRE_HOURS")
    handoff_claimed_expire_hours: int | None = Field(
        default=None, alias="HANDOFF_CLAIMED_EXPIRE_HOURS"
    )
    # The original single knob, kept as the claimed window's default so an
    # existing .env keeps meaning what it meant.
    handoff_expire_hours: int = Field(default=24, alias="HANDOFF_EXPIRE_HOURS")
    handoff_team_group_name: str = Field(default="Gutty Agent", alias="HANDOFF_TEAM_GROUP_NAME")

    @property
    def claimed_expire_hours(self) -> int:
        return self.handoff_claimed_expire_hours or self.handoff_expire_hours

    # Provider: "mock" | "zoho"
    crm_provider: str = Field(default="mock", alias="CRM_PROVIDER")

    # Zoho OAuth (Self Client / Server-based)
    zoho_client_id: str | None = Field(default=None, alias="ZOHO_CLIENT_ID")
    zoho_client_secret: str | None = Field(default=None, alias="ZOHO_CLIENT_SECRET")
    zoho_refresh_token: str | None = Field(default=None, alias="ZOHO_REFRESH_TOKEN")

    # DC: com | eu | in | com.au | jp | ca
    zoho_dc: str = Field(default="com", alias="ZOHO_DC")

    # Set to true to hit sandbox.zohoapis.com instead of www.zohoapis.com
    zoho_sandbox: bool = Field(default=False, alias="ZOHO_SANDBOX")

    @property
    def zoho_accounts_url(self) -> str:
        return f"https://accounts.zoho.{self.zoho_dc}"

    @property
    def zoho_api_base(self) -> str:
        host = "sandbox.zohoapis" if self.zoho_sandbox else "www.zohoapis"
        return f"https://{host}.{self.zoho_dc}/crm/v8"
