"""Invoicing configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class InvoicingSettings(BaseSettings):
    """Settings for the invoicing automation workflow."""

    # Clockify
    clockify_api_key: str
    clockify_base_url: str = "https://api.clockify.me/api/v1"

    # Fakturoid
    fakturoid_client_id: str
    fakturoid_client_secret: str
    fakturoid_slug: str
    fakturoid_subject_name: str
    fakturoid_user_agent: str = "ChaChinkBot"
    fakturoid_base_url: str = "https://app.fakturoid.cz"

    # Slack
    slack_bot_token: str = ""
    slack_channel: str = ""

    # Defaults
    default_hourly_rate: float = 0.0
    default_vat_rate: int = 0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
