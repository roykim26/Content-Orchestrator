from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import InvalidStateError
from app.models.artifact import (
    ArtifactPerformanceUpdate,
    ArtifactRequeueRequest,
    ArtifactReviewRequest,
    ContentArtifact,
)


class ArtifactService:
    def __init__(self, session: Session) -> None:
        self.session = session

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
            self._validate_publish_ready(artifact)
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
        self._validate_publish_ready(artifact)
        artifact.reviewed = True
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
        self._validate_publish_ready(artifact)

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

    def _validate_publish_ready(self, artifact: ContentArtifact) -> None:
        if artifact.platform != "note":
            return
        note_account = str(artifact.extra_metadata.get("note_account") or "").strip()
        if not note_account:
            raise InvalidStateError("note artifact requires note_account before publishing.")
        if note_account not in {"note_a", "note_b"}:
            raise InvalidStateError(
                f"note artifact has unsupported note_account '{note_account}'. Expected note_a or note_b."
            )

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
