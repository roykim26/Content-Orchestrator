from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.ids import generate_id
from app.engines.angle_engine import ContentAngleEngine
from app.engines.distribution_engine import DistributionEngine
from app.engines.topic_engine import TopicEngine
from app.models.artifact import ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic, TopicCreate, TopicUpdate


class TopicService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.topic_engine = TopicEngine()
        self.distribution_engine = DistributionEngine()
        self.angle_engine = ContentAngleEngine()

    def create_topic(self, payload: TopicCreate) -> Topic:
        payload = self.topic_engine.normalize_topic(payload)
        topic = Topic(
            id=generate_id("topic"),
            master_topic=payload.master_topic,
            topic_cluster=payload.topic_cluster,
            business_goal=payload.business_goal,
            target_keyword=payload.target_keyword,
            secondary_keyword=payload.secondary_keyword,
            secondary_keywords=payload.secondary_keywords,
            target_audience=payload.target_audience,
            article_type=payload.article_type,
            content_focus=payload.content_focus,
            scenes=payload.scenes,
            target_url=payload.target_url,
            brand_name=payload.brand_name,
            site=payload.site,
            language=payload.language,
            extra_rules=payload.extra_rules,
            priority=payload.priority,
            target_platforms=payload.target_platforms,
            status=payload.status,
            brief=payload.brief,
            note_account=payload.note_account,
            feishu_record_id=payload.feishu_record_id,
            feishu_topic_id=payload.feishu_topic_id,
        )
        self.session.add(topic)
        self.session.commit()
        self.session.refresh(topic)
        return topic

    def list_topics(self, status: str | None = None) -> list[Topic]:
        statement = select(Topic)
        if status:
            statement = statement.where(Topic.status == status)
        return list(self.session.exec(statement.order_by(Topic.created_at.desc())).all())

    def get_topic(self, topic_id: str) -> Topic | None:
        return self.session.get(Topic, topic_id)

    def update_topic(self, topic_id: str, payload: TopicUpdate) -> Topic | None:
        topic = self.get_topic(topic_id)
        if not topic:
            return None
        updates = payload.model_dump(exclude_unset=True)
        if "target_platforms" in updates and updates["target_platforms"] is not None:
            updates["target_platforms"] = [platform.strip().lower() for platform in updates["target_platforms"]]
        if "secondary_keywords" in updates and updates["secondary_keywords"] is not None:
            updates["secondary_keywords"] = [str(item).strip() for item in updates["secondary_keywords"] if str(item).strip()]
        if "scenes" in updates and updates["scenes"] is not None:
            updates["scenes"] = [str(item).strip() for item in updates["scenes"] if str(item).strip()]
        for key, value in updates.items():
            setattr(topic, key, value)
        topic.updated_at = datetime.now(timezone.utc)
        self.session.add(topic)
        self.session.commit()
        self.session.refresh(topic)
        return topic

    def plan_topic(self, topic_id: str) -> dict[str, object] | None:
        topic = self.get_topic(topic_id)
        if not topic:
            return None

        existing_tasks = list(
            self.session.exec(
                select(DistributionTask).where(DistributionTask.topic_id == topic.id)
            ).all()
        )
        if existing_tasks:
            return {
                "topic_id": topic.id,
                "status": topic.status,
                "task_count": len(existing_tasks),
                "tasks": [
                    {
                        "task_id": task.id,
                        "platform": task.platform,
                        "content_type": task.content_type,
                        "angle": task.angle,
                    }
                    for task in existing_tasks
                ],
                "message": "Topic already planned; existing tasks returned.",
            }

        plans = self.distribution_engine.build_plan(topic)
        created_tasks: list[dict[str, str]] = []
        for plan in plans:
            angle = self.angle_engine.build_angle(topic, plan)
            task = DistributionTask(
                id=generate_id("task"),
                topic_id=topic.id,
                platform=plan.platform,
                task_type="generate_content",
                content_type=plan.content_type,
                objective=plan.objective,
                angle=angle,
                priority=topic.priority,
            )
            self.session.add(task)
            created_tasks.append(
                {
                    "task_id": task.id,
                    "platform": task.platform,
                    "content_type": task.content_type,
                    "angle": task.angle,
                }
            )

        topic.status = "planned"
        topic.updated_at = datetime.now(timezone.utc)
        self.session.add(topic)
        self.session.commit()

        return {
            "topic_id": topic.id,
            "status": topic.status,
            "task_count": len(created_tasks),
            "tasks": created_tasks,
        }

    def get_topic_overview(self, topic_id: str) -> dict[str, object] | None:
        topic = self.get_topic(topic_id)
        if not topic:
            return None

        tasks = list(
            self.session.exec(
                select(DistributionTask)
                .where(DistributionTask.topic_id == topic.id)
                .order_by(DistributionTask.created_at.asc())
            ).all()
        )
        artifacts = list(
            self.session.exec(
                select(ContentArtifact)
                .where(ContentArtifact.topic_id == topic.id)
                .order_by(ContentArtifact.created_at.asc())
            ).all()
        )

        return {
            "topic": {
                "id": topic.id,
                "master_topic": topic.master_topic,
                "topic_cluster": topic.topic_cluster,
                "business_goal": topic.business_goal,
                "target_keyword": topic.target_keyword,
                "priority": topic.priority,
                "target_platforms": topic.target_platforms,
                "status": topic.status,
                "brief": topic.brief,
                "note_account": topic.note_account,
                "feishu_record_id": topic.feishu_record_id,
                "feishu_topic_id": topic.feishu_topic_id,
                "created_at": topic.created_at.isoformat(),
                "updated_at": topic.updated_at.isoformat(),
            },
            "tasks": [
                {
                    "id": task.id,
                    "platform": task.platform,
                    "task_type": task.task_type,
                    "content_type": task.content_type,
                    "objective": task.objective,
                    "angle": task.angle,
                    "status": task.status,
                    "priority": task.priority,
                    "artifact_id": task.artifact_id,
                    "error_message": task.error_message,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                }
                for task in tasks
            ],
            "artifacts": [
                {
                    "id": artifact.id,
                    "task_id": artifact.task_id,
                    "platform": artifact.platform,
                    "content_type": artifact.content_type,
                    "title": artifact.artifact_title,
                    "summary": artifact.artifact_summary,
                    "status": artifact.status,
                    "published": artifact.published,
                    "published_url": artifact.published_url,
                    "reviewed": artifact.reviewed,
                    "publish_attempts": artifact.publish_attempts,
                    "performance": artifact.extra_metadata.get("performance", {}),
                    "created_at": artifact.created_at.isoformat(),
                    "updated_at": artifact.updated_at.isoformat(),
                }
                for artifact in artifacts
            ],
        }
