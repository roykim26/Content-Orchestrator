from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Column, Field, JSON, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DistributionTaskBase(SQLModel):
    topic_id: str
    platform: str
    task_type: str
    content_type: str
    objective: str
    angle: str
    status: str = "pending"
    priority: str = "A"
    depends_on: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    artifact_id: str | None = None
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class DistributionTask(DistributionTaskBase, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DistributionTaskRead(DistributionTaskBase):
    id: str
    created_at: datetime
    updated_at: datetime


class PlannedDistribution(SQLModel):
    platform: str
    content_type: str
    objective: str
