from __future__ import annotations

import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.ids import generate_id
from app.models.artifact import ArtifactPerformanceUpdate, ArtifactPublishResult
from app.models.seo_asset import SEOAssetCreate
from app.models.topic import TopicCreate
from app.services.automated_topic_service import AutomatedTopicService
from app.services.publisher_service import PublisherService
from app.services.seo_service import SEOService
from app.services.task_service import TaskService
from app.services.topic_service import TopicService
from app.feedback.service import TopicFeedbackService
from app.services.artifact_service import ArtifactService


def build_demo_engine():
    return create_engine("sqlite://")


def main() -> None:
    engine = build_demo_engine()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        topic_service = TopicService(session)
        task_service = TaskService(session)
        publisher_service = PublisherService(session)
        artifact_service = ArtifactService(session)
        seo_service = SEOService(session)
        feedback_service = TopicFeedbackService(session)
        automation_service = AutomatedTopicService(session)

        topic = topic_service.create_topic(
            TopicCreate(
                master_topic="How to operationalize content ops automation",
                topic_cluster="real_estate_ai_workflow",
                business_goal="technical_authority",
                target_keyword="content ops automation",
                priority="A",
                target_platforms=["note", "x", "hatena"],
                status="ready",
                brief="Demo topic for internal feedback loop.",
            )
        )
        plan = topic_service.plan_topic(topic.id)

        artifact_ids: list[str] = []
        for task in plan["tasks"]:
            run_result = task_service.run_task(task["task_id"])
            artifact_ids.append(run_result["artifact_id"])

        for artifact_id in artifact_ids[:2]:
            artifact_service.approve_artifact(artifact_id)
            artifact = publisher_service.write_publish_result(
                artifact_id,
                ArtifactPublishResult(
                    published=True,
                    published_url=f"https://example.com/{artifact_id}",
                    external_publish_id=generate_id("pub"),
                    status="published",
                ),
            )
            seo_service.create_asset(
                SEOAssetCreate(
                    artifact_id=artifact.id,
                    topic_id=artifact.topic_id,
                    source_platform=artifact.platform,
                    source_url=artifact.published_url,
                    target_url="https://example.com/landing-page",
                    anchor_text="content ops automation",
                    indexed=True,
                )
            )
            artifact_service.update_performance(
                artifact_id,
                ArtifactPerformanceUpdate(
                    views=600 if artifact.platform == "note" else 320,
                    clicks=42 if artifact.platform == "note" else 19,
                    conversions=6 if artifact.platform == "note" else 2,
                    likes=18 if artifact.platform == "note" else 11,
                    shares=5 if artifact.platform == "note" else 3,
                    comments=4 if artifact.platform == "note" else 2,
                    source="demo_feedback_loop",
                ),
            )

        summary = feedback_service.summarize()
        auto_result = automation_service.run_weekly_selection(force=True)

        print("Feedback summary:")
        print(summary)
        print()
        print("Automated selection result:")
        print(auto_result)


if __name__ == "__main__":
    main()
