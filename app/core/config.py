from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TakkenAI Content Orchestrator"
    app_env: str = "local"
    database_url: str | None = None
    publisher_api_key: str | None = None
    topic_strategy_path: str = "data/topic_strategy.json"
    topic_signal_sources_path: str = "data/topic_signal_sources.json"
    enable_topic_selection_scheduler: bool = True
    topic_selection_cron: str = "0 9 * * 1"
    enable_topic_refill_scheduler: bool = True
    topic_refill_cron: str = "45 16 * * mon-fri"
    publish_autopilot_lanes: str = "note_a,note_b,ameba"
    active_topic_clusters: str = ""
    automation_timezone: str = "Asia/Shanghai"
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_topic_app_token: str | None = None
    feishu_topic_table_id: str | None = None
    feishu_notify_receive_id_type: str | None = None
    feishu_notify_receive_id: str | None = None
    feishu_legacy_topic_app_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FEISHU_LEGACY_TOPIC_APP_TOKEN", "FEISHU_APP_TOKEN"),
    )
    feishu_legacy_topic_table_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FEISHU_LEGACY_TOPIC_TABLE_ID", "FEISHU_TABLE_ID"),
    )
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    llm_temperature: float = 1.0
    llm_max_tokens: int = 4000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
