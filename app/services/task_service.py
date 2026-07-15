from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import ConflictError, InvalidStateError
from app.core.ids import generate_id
from app.core.config import settings
from app.engines.artifact_engine import ArtifactEngine
from app.engines.prompt_engine import PromptEngine
from app.models.artifact import ArtifactGenerationPayload, ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityReport, ContentQualityService
from app.services.fact_review_service import FactReviewReport, FactReviewService


class TaskService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.prompt_engine = PromptEngine()
        self.artifact_engine = ArtifactEngine()
        self.content_quality = ContentQualityService()
        self.fact_review = FactReviewService(self.content_quality.facts)

    def list_tasks(
        self,
        topic_id: str | None = None,
        platform: str | None = None,
        status: str | None = None,
    ) -> list[DistributionTask]:
        statement = select(DistributionTask)
        if topic_id:
            statement = statement.where(DistributionTask.topic_id == topic_id)
        if platform:
            statement = statement.where(DistributionTask.platform == platform.lower())
        if status:
            statement = statement.where(DistributionTask.status == status)
        return list(self.session.exec(statement.order_by(DistributionTask.created_at.desc())).all())

    def run_task(self, task_id: str) -> dict[str, object] | None:
        task = self.session.get(DistributionTask, task_id)
        if not task:
            return None
        if task.artifact_id:
            raise ConflictError(f"Task '{task.id}' already generated artifact '{task.artifact_id}'.")
        if task.status == "completed":
            raise InvalidStateError(f"Task '{task.id}' is already completed.")

        topic = self.session.get(Topic, task.topic_id)
        if not topic:
            task.status = "failed"
            task.error_message = "Topic not found"
            task.updated_at = datetime.now(timezone.utc)
            self.session.add(task)
            self.session.commit()
            return {"task_id": task.id, "status": task.status, "error": task.error_message}

        task.status = "running"
        task.updated_at = datetime.now(timezone.utc)
        self.session.add(task)
        self.session.commit()

        if task.task_type != "generate_content":
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            task.updated_at = datetime.now(timezone.utc)
            self.session.add(task)
            self.session.commit()
            return {"task_id": task.id, "status": task.status}

        prompt_version, system_prompt = self.prompt_engine.get_prompt(task.platform)
        generation_payload = ArtifactGenerationPayload(
            task_id=task.id,
            platform=task.platform,
            content_type=task.content_type,
            objective=task.objective,
            angle=task.angle,
            extra_metadata={
                "prompt_version": prompt_version,
                "system_prompt": system_prompt,
            },
        )
        try:
            artifact_title, artifact_summary, content = self.artifact_engine.generate(generation_payload, topic)
        except Exception as exc:  # noqa: BLE001
            task.status = "failed"
            task.error_message = str(exc)
            task.updated_at = datetime.now(timezone.utc)
            self.session.add(task)
            self.session.commit()
            return {"task_id": task.id, "status": task.status, "error": task.error_message}

        comparison_contents = list(
            self.session.exec(
                select(ContentArtifact.content)
                .where(ContentArtifact.topic_id == topic.id)
                .where(ContentArtifact.platform != task.platform)
            ).all()
        )
        resolved_target_url = self.content_quality.facts.resolve_target_url(topic)
        quality_report = self._evaluate_content(
            title=artifact_title,
            content=content,
            topic=topic,
            platform=task.platform,
            target_url=resolved_target_url,
            comparison_contents=comparison_contents,
        )
        manual_review_required = self.content_quality.facts.requires_manual_review(
            topic,
            title=artifact_title,
            content=content,
        )
        fact_review_required = self.fact_review.should_review(
            topic=topic,
            platform=task.platform,
            title=artifact_title,
            content=content,
        )
        fact_review_history: list[dict[str, object]] = []
        fact_review_report: FactReviewReport | None = None
        rewrite_count = 0
        if fact_review_required:
            for attempt in range(settings.fact_review_max_rewrites + 1):
                fact_review_report = self.fact_review.review(
                    title=artifact_title,
                    summary=artifact_summary,
                    content=content,
                    topic=topic,
                    platform=task.platform,
                    quality_report=quality_report,
                    attempt=attempt,
                )
                fact_review_history.append(fact_review_report.as_dict())
                if fact_review_report.approved:
                    break
                if fact_review_report.decision != "rewrite_required" or attempt >= settings.fact_review_max_rewrites:
                    break
                try:
                    repaired = self.fact_review.rewrite(
                        title=artifact_title,
                        summary=artifact_summary,
                        content=content,
                        topic=topic,
                        platform=task.platform,
                        report=fact_review_report,
                    )
                    artifact_title, artifact_summary, content = self.artifact_engine._postprocess_generated_result(
                        repaired,
                        generation_payload,
                        topic,
                    )
                    self.artifact_engine._validate_generated_content(
                        (artifact_title, artifact_summary, content),
                        platform=task.platform,
                    )
                except Exception as exc:  # noqa: BLE001
                    fact_review_report = FactReviewReport(
                        reviewer=self.fact_review.reviewer_id,
                        model=self.fact_review.model,
                        decision="blocked",
                        score=0,
                        blocking_errors=[f"Automatic fact repair failed safely: {exc}"],
                        facts_version=self.content_quality.facts.version,
                        attempt=attempt,
                    )
                    fact_review_history.append(fact_review_report.as_dict())
                    break
                rewrite_count += 1
                quality_report = self._evaluate_content(
                    title=artifact_title,
                    content=content,
                    topic=topic,
                    platform=task.platform,
                    target_url=resolved_target_url,
                    comparison_contents=comparison_contents,
                )
                manual_review_required = self.content_quality.facts.requires_manual_review(
                    topic,
                    title=artifact_title,
                    content=content,
                )

        bot_approved = bool(fact_review_report and fact_review_report.approved)
        if fact_review_required:
            initial_status = "publish_pending" if bot_approved else "rejected"
            reviewed = bot_approved
            reviewed_by = fact_review_report.reviewer if bot_approved and fact_review_report else None
        else:
            initial_status = "review_pending" if manual_review_required or quality_report.publish_blocked else "generated"
            reviewed = False
            reviewed_by = None

        review_messages = quality_report.errors + quality_report.warnings
        if fact_review_report:
            review_messages += fact_review_report.blocking_errors + fact_review_report.warnings
        review_notes = " | ".join(dict.fromkeys(review_messages)) or None

        artifact = ContentArtifact(
            id=generate_id("art"),
            topic_id=task.topic_id,
            task_id=task.id,
            platform=task.platform,
            content_type=task.content_type,
            angle=task.angle,
            artifact_title=artifact_title,
            artifact_summary=artifact_summary,
            content=content,
            prompt_version=prompt_version,
            generation_model=self.artifact_engine.generation_model,
            status=initial_status,
            reviewed=reviewed,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
            extra_metadata={
                "objective": task.objective,
                "target_keyword": topic.target_keyword,
                "secondary_keyword": topic.secondary_keyword or "",
                "secondary_keywords": topic.secondary_keywords,
                "target_audience": topic.target_audience or "",
                "article_type": topic.article_type or "",
                "content_focus": topic.content_focus or "",
                "scenes": topic.scenes,
                "target_url": topic.target_url or "",
                "brand_name": topic.brand_name or "",
                "site": topic.site or "",
                "language": topic.language or "",
                "extra_rules": topic.extra_rules or "",
                "topic_cluster": topic.topic_cluster,
                "business_goal": topic.business_goal,
                "priority": topic.priority,
                "account": topic.note_account or "",
                "note_account": topic.note_account or "",
                "source_topic_id": topic.id,
                "target_platforms": topic.target_platforms,
                "resolved_target_url": resolved_target_url,
                "product_facts_version": self.content_quality.facts.version,
                "platform_role": self.content_quality.facts.platform_role(task.platform),
                "manual_review_required": manual_review_required,
                "quality_report": quality_report.as_dict(),
                "fact_review_required": fact_review_required,
                "fact_review_approved": bot_approved,
                "fact_review_report": fact_review_report.as_dict() if fact_review_report else None,
                "fact_review_history": fact_review_history,
                "fact_review_rewrite_count": rewrite_count,
            },
        )

        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)

        task.status = "completed"
        task.artifact_id = artifact.id
        task.completed_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        self.session.add(task)
        self.session.commit()

        return {
            "task_id": task.id,
            "status": task.status,
            "artifact_id": artifact.id,
        }

    def _evaluate_content(
        self,
        *,
        title: str,
        content: str,
        topic: Topic,
        platform: str,
        target_url: str,
        comparison_contents: list[str],
    ) -> ContentQualityReport:
        return self.content_quality.evaluate(
            title=title,
            content=content,
            topic=topic,
            platform=platform,
            target_url=target_url,
            comparison_contents=comparison_contents,
        )

    def retry_task(self, task_id: str) -> dict[str, object] | None:
        task = self.session.get(DistributionTask, task_id)
        if not task:
            return None
        task.status = "pending"
        task.error_message = None
        task.updated_at = datetime.now(timezone.utc)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return {"task_id": task.id, "status": task.status}
