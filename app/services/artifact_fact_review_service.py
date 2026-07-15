from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.core.exceptions import InvalidStateError
from app.engines.artifact_engine import ArtifactEngine
from app.models.artifact import ArtifactGenerationPayload, ContentArtifact
from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityService
from app.services.fact_review_service import FactReviewReport, FactReviewService


class ArtifactFactReviewService:
    """Runs independent fact review and repair for an already stored artifact."""

    REVIEWABLE_STATUSES = {"generated", "review_pending", "rejected"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.quality = ContentQualityService()
        self.reviewer = FactReviewService(self.quality.facts)
        self.artifact_engine = ArtifactEngine()

    def review_artifact(self, artifact_id: str) -> ContentArtifact | None:
        artifact = self.session.get(ContentArtifact, artifact_id)
        if not artifact:
            return None
        if artifact.status not in self.REVIEWABLE_STATUSES:
            raise InvalidStateError(
                f"Artifact in status '{artifact.status}' cannot enter automated fact review."
            )
        topic = self.session.get(Topic, artifact.topic_id)
        if not topic:
            raise InvalidStateError("Artifact topic is missing; fact review cannot run.")

        comparisons = list(
            self.session.exec(
                select(ContentArtifact.content)
                .where(ContentArtifact.topic_id == artifact.topic_id)
                .where(ContentArtifact.id != artifact.id)
                .where(ContentArtifact.platform != artifact.platform)
            ).all()
        )
        target_url = self.quality.facts.resolve_target_url(topic)
        title = artifact.artifact_title or topic.master_topic
        summary = artifact.artifact_summary or ""
        content = artifact.content
        history: list[dict[str, object]] = list(artifact.extra_metadata.get("fact_review_history") or [])
        rewrite_count = int(artifact.extra_metadata.get("fact_review_rewrite_count") or 0)
        report: FactReviewReport | None = None

        payload = ArtifactGenerationPayload(
            task_id=artifact.task_id,
            platform=artifact.platform,
            content_type=artifact.content_type,
            objective=str(artifact.extra_metadata.get("objective") or "fact_repair"),
            angle=artifact.angle,
        )
        for attempt in range(settings.fact_review_max_rewrites + 1):
            quality_report = self.quality.evaluate(
                title=title,
                content=content,
                topic=topic,
                platform=artifact.platform,
                target_url=target_url,
                comparison_contents=comparisons,
            )
            report = self.reviewer.review(
                title=title,
                summary=summary,
                content=content,
                topic=topic,
                platform=artifact.platform,
                quality_report=quality_report,
                attempt=attempt,
            )
            history.append(report.as_dict())
            if report.approved:
                break
            if report.decision != "rewrite_required" or attempt >= settings.fact_review_max_rewrites:
                break
            try:
                repaired = self.reviewer.rewrite(
                    title=title,
                    summary=summary,
                    content=content,
                    topic=topic,
                    platform=artifact.platform,
                    report=report,
                )
                title, summary, content = self.artifact_engine._postprocess_generated_result(
                    repaired,
                    payload,
                    topic,
                )
                self.artifact_engine._validate_generated_content(
                    (title, summary, content),
                    platform=artifact.platform,
                )
            except Exception as exc:  # noqa: BLE001
                report = FactReviewReport(
                    reviewer=self.reviewer.reviewer_id,
                    model=self.reviewer.model,
                    decision="blocked",
                    score=0,
                    blocking_errors=[f"Automatic fact repair failed safely: {exc}"],
                    facts_version=self.quality.facts.version,
                    attempt=attempt,
                )
                history.append(report.as_dict())
                break
            rewrite_count += 1

        final_quality = self.quality.evaluate(
            title=title,
            content=content,
            topic=topic,
            platform=artifact.platform,
            target_url=target_url,
            comparison_contents=comparisons,
        )
        approved = bool(report and report.approved and not final_quality.publish_blocked)
        artifact.artifact_title = title
        artifact.artifact_summary = summary
        artifact.content = content
        artifact.reviewed = approved
        artifact.reviewed_by = report.reviewer if approved and report else None
        artifact.status = "publish_pending" if approved else "rejected"
        messages = final_quality.errors + final_quality.warnings
        if report:
            messages += report.blocking_errors + report.warnings
        artifact.review_notes = " | ".join(dict.fromkeys(messages)) or None
        artifact.extra_metadata = {
            **artifact.extra_metadata,
            "resolved_target_url": target_url,
            "product_facts_version": self.quality.facts.version,
            "manual_review_required": self.quality.facts.requires_manual_review(
                topic,
                title=title,
                content=content,
            ),
            "quality_report": final_quality.as_dict(),
            "fact_review_required": True,
            "fact_review_approved": approved,
            "fact_review_report": report.as_dict() if report else None,
            "fact_review_history": history,
            "fact_review_rewrite_count": rewrite_count,
            "fact_reviewed_at": datetime.now(timezone.utc).isoformat(),
            "automation_blocked": not approved,
        }
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact
