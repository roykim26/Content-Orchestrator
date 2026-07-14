from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.artifact import ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic
from app.services.task_service import TaskService


class ContentReviewFlowTests(unittest.TestCase):
    def test_product_usage_article_waits_for_named_human_review(self) -> None:
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
            with patch("app.engines.artifact_engine.ArtifactEngine.generate", return_value=generated):
                result = TaskService(session).run_task(task.id)

            artifact = session.get(ContentArtifact, result["artifact_id"])
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact.status, "review_pending")
            self.assertFalse(artifact.reviewed)
            self.assertTrue(artifact.extra_metadata["manual_review_required"])
            self.assertGreaterEqual(artifact.extra_metadata["quality_report"]["score"], 75)


if __name__ == "__main__":
    unittest.main()
