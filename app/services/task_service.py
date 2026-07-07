from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import ConflictError, InvalidStateError
from app.core.ids import generate_id
from app.engines.artifact_engine import ArtifactEngine
from app.engines.prompt_engine import PromptEngine
from app.models.artifact import ArtifactGenerationPayload, ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic


class TaskService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.prompt_engine = PromptEngine()
        self.artifact_engine = ArtifactEngine()

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
            status="publish_pending" if task.platform == "ameba" else "generated",
            reviewed=task.platform == "ameba",
            reviewed_by="ameba-auto-generation" if task.platform == "ameba" else None,
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
