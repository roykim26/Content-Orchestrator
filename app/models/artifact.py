from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator
from sqlmodel import Column, Field, JSON, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContentArtifactBase(SQLModel):
    topic_id: str
    task_id: str
    platform: str
    content_type: str
    angle: str
    artifact_title: str | None = None
    artifact_summary: str | None = None
    content: str
    format: str = "markdown"
    prompt_version: str = "v0"
    generation_model: str = "placeholder"
    status: str = "generated"
    reviewed: bool = False
    reviewed_by: str | None = None
    review_notes: str | None = None
    published: bool = False
    claimed_by: str | None = None
    publish_started_at: datetime | None = None
    publish_attempts: int = 0
    published_url: str | None = None
    external_publish_id: str | None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    version: int = 1


class ContentArtifact(ContentArtifactBase, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ArtifactRead(ContentArtifactBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class ArtifactApiRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_id: str
    task_id: str
    platform: str
    content_type: str
    angle: str
    title: str | None
    summary: str | None
    content: str
    format: str
    prompt_version: str
    generation_model: str
    status: str
    reviewed: bool
    reviewed_by: str | None
    review_notes: str | None
    published: bool
    claimed_by: str | None
    publish_started_at: datetime | None
    publish_attempts: int
    published_url: str | None
    external_publish_id: str | None
    metadata: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, artifact: "ContentArtifact") -> "ArtifactApiRead":
        return cls(
            id=artifact.id,
            topic_id=artifact.topic_id,
            task_id=artifact.task_id,
            platform=artifact.platform,
            content_type=artifact.content_type,
            angle=artifact.angle,
            title=artifact.artifact_title,
            summary=artifact.artifact_summary,
            content=artifact.content,
            format=artifact.format,
            prompt_version=artifact.prompt_version,
            generation_model=artifact.generation_model,
            status=artifact.status,
            reviewed=artifact.reviewed,
            reviewed_by=artifact.reviewed_by,
            review_notes=artifact.review_notes,
            published=artifact.published,
            claimed_by=artifact.claimed_by,
            publish_started_at=artifact.publish_started_at,
            publish_attempts=artifact.publish_attempts,
            published_url=artifact.published_url,
            external_publish_id=artifact.external_publish_id,
            metadata=artifact.extra_metadata,
            version=artifact.version,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )


class ArtifactReviewRequest(SQLModel):
    reviewed: bool = True
    reviewed_by: str | None = None
    review_notes: str | None = None
    status: str = "review_pending"


class ArtifactPublishResult(SQLModel):
    published: bool
    published_url: str | None = None
    external_publish_id: str | None = None
    status: str = "published"
    error_message: str | None = None


class ArtifactPerformanceUpdate(SQLModel):
    views: int | None = None
    clicks: int | None = None
    conversions: int | None = None
    likes: int | None = None
    shares: int | None = None
    comments: int | None = None
    captured_at: datetime | None = None
    source: str | None = None


class ArtifactRequeueRequest(SQLModel):
    requested_by: str | None = None
    reason: str | None = None
    clear_error: bool = False


class ArtifactClaimRequest(SQLModel):
    platform: str
    consumer_name: str
    limit: int = 1
    account: str | None = None
    note_account: str | None = None
    dry_run: bool = False

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return value.lower()

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("note_account")
    @classmethod
    def normalize_note_account(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None


class ArtifactClaimResponse(BaseModel):
    consumer_name: str
    claimed_count: int
    artifacts: list["ArtifactPublishEnvelope"]


class ArtifactGenerationPayload(SQLModel):
    task_id: str
    platform: str
    content_type: str
    objective: str
    angle: str
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactPublishEnvelope(BaseModel):
    artifact_id: str
    topic_id: str
    platform: str
    content_type: str
    title: str | None
    summary: str | None
    content: str
    format: str
    status: str
    metadata: dict[str, Any]

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return value.lower()

    @classmethod
    def from_model(cls, artifact: "ContentArtifact") -> "ArtifactPublishEnvelope":
        return cls(
            artifact_id=artifact.id,
            topic_id=artifact.topic_id,
            platform=artifact.platform,
            content_type=artifact.content_type,
            title=artifact.artifact_title,
            summary=artifact.artifact_summary,
            content=artifact.content,
            format=artifact.format,
            status=artifact.status,
            metadata=artifact.extra_metadata,
        )
