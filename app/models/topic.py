from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Column, Field, JSON, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TopicBase(SQLModel):
    master_topic: str
    topic_cluster: str
    business_goal: str
    target_keyword: str
    secondary_keyword: str | None = None
    secondary_keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    target_audience: str | None = None
    article_type: str | None = None
    content_focus: str | None = None
    scenes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    target_url: str | None = None
    brand_name: str | None = None
    site: str | None = None
    language: str | None = None
    extra_rules: str | None = None
    priority: str = "A"
    target_platforms: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "draft"
    brief: str | None = None
    note_account: str | None = None
    feishu_record_id: str | None = None
    feishu_topic_id: str | None = None


class Topic(TopicBase, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TopicCreate(TopicBase):
    pass


class TopicUpdate(SQLModel):
    master_topic: str | None = None
    topic_cluster: str | None = None
    business_goal: str | None = None
    target_keyword: str | None = None
    secondary_keyword: str | None = None
    secondary_keywords: list[str] | None = None
    target_audience: str | None = None
    article_type: str | None = None
    content_focus: str | None = None
    scenes: list[str] | None = None
    target_url: str | None = None
    brand_name: str | None = None
    site: str | None = None
    language: str | None = None
    extra_rules: str | None = None
    priority: str | None = None
    target_platforms: list[str] | None = None
    status: str | None = None
    brief: str | None = None
    note_account: str | None = None
    feishu_record_id: str | None = None
    feishu_topic_id: str | None = None


class TopicRead(TopicBase):
    id: str
    created_at: datetime
    updated_at: datetime
