from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import InvalidStateError
from app.core.config import settings
from app.models.artifact import (
    ArtifactPerformanceUpdate,
    ArtifactRequeueRequest,
    ArtifactReviewRequest,
    ContentArtifact,
)
from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityService


class ArtifactService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.content_quality = ContentQualityService()

    def list_artifacts(
        self,
        topic_id: str | None = None,
        platform: str | None = None,
        status: str | None = None,
    ) -> list[ContentArtifact]:
        statement = select(ContentArtifact)
        if topic_id:
            statement = statement.where(ContentArtifact.topic_id == topic_id)
        if platform:
            statement = statement.where(ContentArtifact.platform == platform)
        if status:
            statement = statement.where(ContentArtifact.status == status)
        return list(self.session.exec(statement.order_by(ContentArtifact.created_at.desc())).all())

    def get_artifact(self, artifact_id: str) -> ContentArtifact | None:
        return self.session.get(ContentArtifact, artifact_id)

    def review_artifact(
        self,
        artifact_id: str,
        payload: ArtifactReviewRequest,
    ) -> ContentArtifact | None:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return None
        if payload.status == "publish_pending" and not payload.reviewed:
            raise InvalidStateError("Artifact must be reviewed before entering publish_pending state.")
        if payload.status == "publish_pending":
            if not str(payload.reviewed_by or "").strip():
                raise InvalidStateError("Manual review requires reviewed_by before publishing.")
            self._validate_publish_ready(artifact, automated=False)
        artifact.reviewed = payload.reviewed
        artifact.reviewed_by = payload.reviewed_by
        artifact.review_notes = payload.review_notes
        artifact.status = payload.status
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def approve_artifact(self, artifact_id: str) -> ContentArtifact | None:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return None
        if artifact.status not in {"generated", "review_pending", "rejected"}:
            raise InvalidStateError(
                f"Artifact in status '{artifact.status}' cannot be approved for publishing."
            )
        self._validate_publish_ready(artifact, automated=True)
        artifact.reviewed = True
        artifact.reviewed_by = "publish-autopilot-quality-gate"
        artifact.status = "publish_pending"
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def requeue_artifact(
        self,
        artifact_id: str,
        payload: ArtifactRequeueRequest,
    ) -> ContentArtifact | None:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return None
        if artifact.status not in {"failed", "publishing", "draft_created"}:
            raise InvalidStateError(
                f"Artifact in status '{artifact.status}' cannot be re-queued for publishing."
            )
        if not artifact.reviewed:
            raise InvalidStateError("Artifact must be reviewed before re-queueing for publishing.")
        self._validate_publish_ready(artifact, automated=False)

        note_parts: list[str] = []
        if payload.reason:
            note_parts.append(payload.reason)
        if payload.requested_by:
            note_parts.append(f"requeued_by={payload.requested_by}")
        if note_parts:
            artifact.extra_metadata = {
                **artifact.extra_metadata,
                "last_requeue_note": " | ".join(note_parts),
                "last_requeue_at": datetime.now(timezone.utc).isoformat(),
            }

        if payload.clear_error:
            artifact.review_notes = None

        artifact.published = False
        artifact.published_url = None
        artifact.external_publish_id = None
        artifact.claimed_by = None
        artifact.publish_started_at = None
        artifact.status = "publish_pending"
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def requires_manual_review(self, artifact: ContentArtifact) -> bool:
        topic = self.session.get(Topic, artifact.topic_id)
        if not topic:
            return bool(artifact.extra_metadata.get("manual_review_required"))
        return self.content_quality.facts.requires_manual_review(
            topic,
            title=artifact.artifact_title or "",
            content=artifact.content,
        )

    @staticmethod
    def trusted_fact_reviewer_ids() -> set[str]:
        return {
            item.strip()
            for item in str(settings.trusted_fact_reviewer_ids or "").split(",")
            if item.strip()
        }

    def has_trusted_fact_review(self, artifact: ContentArtifact) -> bool:
        reviewer = str(artifact.reviewed_by or "").strip()
        report = artifact.extra_metadata.get("fact_review_report")
        if reviewer not in self.trusted_fact_reviewer_ids() or not isinstance(report, dict):
            return False
        try:
            score = int(report.get("score", 0))
        except (TypeError, ValueError):
            return False
        return (
            artifact.reviewed
            and str(report.get("reviewer") or "").strip() == reviewer
            and str(report.get("decision") or "").strip() == "approved"
            and not list(report.get("blocking_errors") or [])
            and score >= settings.fact_review_min_score
            and str(report.get("facts_version") or "") == self.content_quality.facts.version
        )

    def defer_for_review(self, artifact: ContentArtifact, reason: str) -> ContentArtifact:
        artifact.status = "review_pending"
        artifact.reviewed = False
        artifact.reviewed_by = None
        artifact.review_notes = reason
        artifact.extra_metadata = {
            **artifact.extra_metadata,
            "manual_review_required": True,
        }
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def _validate_publish_ready(self, artifact: ContentArtifact, *, automated: bool) -> None:
        if artifact.platform == "note":
            note_account = str(artifact.extra_metadata.get("note_account") or "").strip()
            if not note_account:
                raise InvalidStateError("note artifact requires note_account before publishing.")
            if note_account not in {"note_a", "note_b"}:
                raise InvalidStateError(
                    f"note artifact has unsupported note_account '{note_account}'. Expected note_a or note_b."
                )

        topic = self.session.get(Topic, artifact.topic_id)
        if not topic:
            raise InvalidStateError("Artifact topic is missing; content quality cannot be verified.")
        if self.requires_manual_review(artifact) and not self.has_trusted_fact_review(artifact):
            raise InvalidStateError("Artifact requires a trusted fact review before publishing.")

        comparisons = list(
            self.session.exec(
                select(ContentArtifact.content)
                .where(ContentArtifact.topic_id == artifact.topic_id)
                .where(ContentArtifact.id != artifact.id)
                .where(ContentArtifact.platform != artifact.platform)
            ).all()
        )
        target_url = self.content_quality.facts.resolve_target_url(topic)
        report = self.content_quality.evaluate(
            title=artifact.artifact_title or "",
            content=artifact.content,
            topic=topic,
            platform=artifact.platform,
            target_url=target_url,
            comparison_contents=comparisons,
        )
        artifact.extra_metadata = {
            **artifact.extra_metadata,
            "resolved_target_url": target_url,
            "product_facts_version": self.content_quality.facts.version,
            "manual_review_required": self.requires_manual_review(artifact),
            "quality_report": report.as_dict(),
        }
        if report.publish_blocked:
            details = " | ".join(report.errors + report.warnings)
            raise InvalidStateError(f"Artifact failed content quality gate ({report.score}/100): {details}")

    def update_performance(
        self,
        artifact_id: str,
        payload: ArtifactPerformanceUpdate,
    ) -> ContentArtifact | None:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return None

        performance = dict(artifact.extra_metadata.get("performance", {}))
        updates = payload.model_dump(exclude_none=True)
        if "captured_at" in updates and updates["captured_at"] is not None:
            updates["captured_at"] = updates["captured_at"].isoformat()
        performance.update(updates)

        artifact.extra_metadata = {
            **artifact.extra_metadata,
            "performance": performance,
        }
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact
