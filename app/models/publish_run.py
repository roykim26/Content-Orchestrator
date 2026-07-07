from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Column, Field, JSON, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublishRunBase(SQLModel):
    lane: str
    platform: str
    account: str | None = None
    status: str = "running"
    stage: str = "started"
    artifact_id: str | None = None
    topic_id: str | None = None
    error_message: str | None = None
    summary: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class PublishRun(PublishRunBase, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PublishRunRead(PublishRunBase):
    id: str
    created_at: datetime
    updated_at: datetime
