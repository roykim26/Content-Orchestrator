from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Column, Field, JSON, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationRunBase(SQLModel):
    automation_type: str
    run_key: str
    status: str = "pending"
    summary: dict[str, object] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AutomationRun(AutomationRunBase, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AutomationRunRead(AutomationRunBase):
    id: str
    created_at: datetime
    updated_at: datetime
