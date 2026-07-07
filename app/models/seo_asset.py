from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SEOAssetBase(SQLModel):
    artifact_id: str
    topic_id: str
    source_platform: str
    source_url: str
    target_url: str
    anchor_text: str
    rd_domain: str
    indexed: bool = False


class SEOAsset(SEOAssetBase, table=True):
    id: str = Field(primary_key=True)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_checked_at: datetime | None = None


class SEOAssetCreate(SQLModel):
    artifact_id: str
    topic_id: str
    source_platform: str
    source_url: str
    target_url: str
    anchor_text: str
    indexed: bool = False


class SEOAssetRead(SEOAssetBase):
    id: str
    first_seen_at: datetime
    last_checked_at: datetime | None = None
