from __future__ import annotations

import unittest

from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityService


class ContentQualityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ContentQualityService()
        self.topic = Topic(
            id="topic_quality",
            master_topic="Ukamiruで資格試験の問題演習を始める方法",
            topic_cluster="qualification_study_method",
            business_goal="study_method_demand",
            target_keyword="独学 資格試験 問題演習",
            target_url="https://www.ukamiru.jp/",
        )

    def test_blocks_verbatim_space_separated_japanese_query(self) -> None:
        report = self.service.evaluate(
            title="資格試験の問題演習を始める方法",
            content="独学 資格試験 問題演習を成功させましょう。",
            topic=self.topic,
            platform="ameba",
        )

        self.assertTrue(report.publish_blocked)
        self.assertEqual(report.checks["exact_spaced_keyword_count"], 1)

    def test_blocks_how_to_title_without_real_steps(self) -> None:
        report = self.service.evaluate(
            title="Ukamiruの使い方",
            content="## 概要\n\n具体的に学びます。\n\n## 注意\n\n選択肢を確認します。",
            topic=self.topic,
            platform="hatena",
        )

        self.assertTrue(report.publish_blocked)
        self.assertEqual(report.checks["promised_step_count"], 0)

    def test_blocks_unverified_product_claim(self) -> None:
        report = self.service.evaluate(
            title="Ukamiruで復習する",
            content="## 復習\n\n週間ごとの正答率推移を確認できます。\n\n## 注意\n\n具体的に確認します。",
            topic=self.topic,
            platform="note",
        )

        self.assertTrue(report.publish_blocked)
        self.assertIn("週間ごとの正答率推移", report.checks["forbidden_claim_matches"])

    def test_resolves_exam_specific_deep_link(self) -> None:
        topic = self.topic.model_copy(
            update={
                "master_topic": "ITパスポートの問題演習を始める方法",
                "target_keyword": "ITパスポート 問題演習",
            }
        )

        self.assertEqual(
            self.service.facts.resolve_target_url(topic),
            "https://itpass.ukamiru.jp/",
        )


if __name__ == "__main__":
    unittest.main()
