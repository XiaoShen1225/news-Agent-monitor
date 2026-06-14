"""Pydantic v2 schema for config.yaml validation.

Startup validation prevents silent failures from typos or missing fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 4096
    max_retries: int = 3
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class TargetConfig(BaseModel):
    url: str
    name: str
    interval_minutes: int = 60
    use_browser: bool = False
    profile: dict | None = None


class SchedulerConfig(BaseModel):
    default_interval_minutes: int = 60
    max_concurrent_runs: int = 3


class StorageConfig(BaseModel):
    history_dir: str = "data/history"
    db_path: str = "data/monitor.db"
    max_snapshots_per_site: int = 50


class AnomalyAlertConfig(BaseModel):
    enabled: bool = True
    zscore_threshold: float = 2.5
    baseline_snapshots: int = 10
    cooldown_minutes: int = 120


class SentimentAlertConfig(BaseModel):
    enabled: bool = True
    shift_threshold: float = 0.3


class AlertsConfig(BaseModel):
    anomaly: AnomalyAlertConfig = Field(default_factory=AnomalyAlertConfig)
    sentiment: SentimentAlertConfig = Field(default_factory=SentimentAlertConfig)


class WatchConfig(BaseModel):
    similarity_threshold: float = 0.7
    match_cooldown_hours: int = 12
    stale_prompt_days: int = 14


class DingTalkNotifier(BaseModel):
    webhook_url: str
    secret: str = ""


class WeComNotifier(BaseModel):
    webhook_url: str


class EmailNotifier(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    to_addrs: list[str]


class TelegramNotifierCfg(BaseModel):
    bot_token: str
    chat_id: str


class NotificationPolicyConfig(BaseModel):
    quiet_start: str = ""  # e.g. "23:00"
    quiet_end: str = ""  # e.g. "07:00"
    dedup_cooldown_minutes: int = 120


class NotificationsConfig(BaseModel):
    dingtalk: list[DingTalkNotifier] = Field(default_factory=list)
    wecom: list[WeComNotifier] = Field(default_factory=list)
    email: list[EmailNotifier] = Field(default_factory=list)
    telegram: list[TelegramNotifierCfg] = Field(default_factory=list)
    policy: NotificationPolicyConfig = Field(default_factory=NotificationPolicyConfig)


class DashboardConfig(BaseModel):
    token: str = ""


class AutoReportConfig(BaseModel):
    enabled: bool = False
    schedule_hour: int = Field(default=9, ge=0, le=23)
    schedule_minute: int = Field(default=0, ge=0, le=59)
    include_sites: list[str] = Field(default_factory=list)


class ChatConfig(BaseModel):
    max_tool_rounds: int = 3
    max_history_tokens: int = 12000
    min_exchanges: int = 1
    compression_threshold: float = 0.6
    compression_target: float = 0.4
    max_tool_results: int = 5
    auto_report: AutoReportConfig = Field(default_factory=AutoReportConfig)


class MemoryConfig(BaseModel):
    cycle_minutes: int = 30
    l1_min_events: int = 5
    l1_cooldown_hours: int = 2
    l2_cooldown_hours: int = 24


class SearchConfig(BaseModel):
    rrf_k: int = 60
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    bm25_top_k: int = 50
    vector_top_k: int = 50


class AppConfig(BaseModel):
    """Root config model.  Parse with AppConfig.model_validate(raw_dict)."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    targets: list[TargetConfig] = Field(default_factory=list, min_length=1)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    notifications: NotificationsConfig | None = None
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)

    @model_validator(mode="after")
    def _check_targets_not_empty(self):
        if not self.targets:
            raise ValueError(
                "config.yaml must define at least one target under 'targets:'"
            )
        return self


def validate_config(raw: dict) -> AppConfig:
    """Return validated AppConfig or raise ValidationError with path hints."""
    return AppConfig.model_validate(raw)
