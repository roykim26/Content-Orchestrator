from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.artifact import ArtifactClaimRequest, ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic
from app.services.task_service import TaskService
from app.services.fact_review_service import FactReviewReport
from app.services.publisher_service import PublisherService
from app.services.artifact_fact_review_service import ArtifactFactReviewService


class ContentReviewFlowTests(unittest.TestCase):
    def test_product_usage_article_is_approved_by_trusted_fact_bot(self) -> None:
        database = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(database)
        with Session(database) as session:
            topic = Topic(
                id="topic_product_review",
                master_topic="Ukamiruで問題演習を始める5ステップ",
                topic_cluster="exam_module_launch",
                business_goal="module_activation",
                target_keyword="独学 資格試験 問題演習",
                target_url="https://www.ukamiru.jp/",
                target_platforms=["ameba"],
                status="planned",
            )
            task = DistributionTask(
                id="task_product_review",
                topic_id=topic.id,
                platform="ameba",
                task_type="generate_content",
                content_type="article",
                objective="brand_awareness",
                angle="使用体験",
                status="pending",
            )
            session.add(topic)
            session.add(task)
            session.commit()

            generated = (
                "Ukamiruで問題演習を始める5ステップ",
                "資格試験の問題演習を始め、解説と弱点復習を活用する流れを紹介します。",
                "問題演習を始める場面を具体的に見ていきます。\n\n"
                "## ステップ1 資格を選ぶ\n\n受験する資格を選びます。\n\n"
                "## ステップ2 問題を解く\n\n選択肢を確認して問題を解きます。\n\n"
                "## ステップ3 解説を読む\n\nすべての選択肢の理由を確認します。\n\n"
                "## ステップ4 弱点を復習する\n\n弱点バンクで間違いを復習します。\n\n"
                "## ステップ5 模試で確認する\n\n模試で仕上がりを確認します。\n\n"
                "[Ukamiruで資格試験を選ぶ](https://www.ukamiru.jp/)"
            )
            bot_report = FactReviewReport(
                reviewer="fact-review-bot-v1",
                model="review-model",
                decision="approved",
                score=96,
                verified_claims=["Ukamiruの確認済み機能のみを記載"],
                facts_version="2026-07-15",
            )
            with (
                patch("app.engines.artifact_engine.ArtifactEngine.generate", return_value=generated),
                patch("app.services.fact_review_service.FactReviewService.review", return_value=bot_report),
            ):
                result = TaskService(session).run_task(task.id)

            artifact = session.get(ContentArtifact, result["artifact_id"])
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.status, "publish_pending")
            self.assertTrue(artifact.reviewed)
            self.assertEqual(artifact.reviewed_by, "fact-review-bot-v1")
            self.assertTrue(artifact.extra_metadata["manual_review_required"])
            self.assertTrue(artifact.extra_metadata["fact_review_approved"])
            self.assertGreaterEqual(artifact.extra_metadata["quality_report"]["score"], 75)

            claimed = PublisherService(session).claim_artifacts(
                ArtifactClaimRequest(
                    platform="ameba",
                    consumer_name="ameba-publisher-test",
                    limit=1,
                )
            )
            self.assertEqual([item.id for item in claimed], [artifact.id])
            self.assertEqual(claimed[0].status, "publishing")

    def test_existing_review_pending_artifact_can_be_fact_reviewed(self) -> None:
        database = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(database)
        with Session(database) as session:
            topic = Topic(
                id="topic_existing_review",
                master_topic="Ukamiruの新機能を確認する",
                topic_cluster="exam_module_launch",
                business_goal="module_activation",
                target_keyword="Ukamiru 新機能",
                target_url="https://www.ukamiru.jp/",
                target_platforms=["ameba"],
                status="planned",
            )
            artifact = ContentArtifact(
                id="artifact_existing_review",
                topic_id=topic.id,
                task_id="task_existing_review",
                platform="ameba",
                content_type="article",
                angle="使用体験",
                artifact_title="Ukamiruで問題演習を確認する",
                artifact_summary="問題演習と復習の流れを確認します。",
                content=(
                    "## 問題演習\n\n具体的に選択肢の理由を確認します。\n\n"
                    "## 弱点復習\n\n弱点バンクで間違いを復習します。\n\n"
                    "[Ukamiru](https://www.ukamiru.jp/)"
                ),
                status="review_pending",
            )
            session.add(topic)
            session.add(artifact)
            session.commit()
            report = FactReviewReport(
                reviewer="fact-review-bot-v1",
                model="review-model",
                decision="approved",
                score=97,
                verified_claims=["確認済み製品機能"],
                facts_version="2026-07-15",
            )

            with patch(
                "app.services.fact_review_service.FactReviewService.review",
                return_value=report,
            ):
                reviewed = ArtifactFactReviewService(session).review_artifact(artifact.id)

            self.assertIsNotNone(reviewed)
            self.assertEqual(reviewed.status, "publish_pending")
            self.assertTrue(reviewed.reviewed)
            self.assertEqual(reviewed.reviewed_by, "fact-review-bot-v1")
            self.assertTrue(reviewed.extra_metadata["fact_review_approved"])


if __name__ == "__main__":
    unittest.main()
