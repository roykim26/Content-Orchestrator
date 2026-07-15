from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityService
from app.services.fact_review_service import FactReviewService


class FactReviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quality = ContentQualityService()
        self.service = FactReviewService(self.quality.facts)
        self.topic = Topic(
            id="topic_takken_fact_review",
            master_topic="宅建業法の37条書面を覚える方法",
            topic_cluster="takken_exam_prep",
            business_goal="seo_backlink",
            target_keyword="宅建 37条書面 覚え方",
            target_url="https://www.takkenai.jp/takken/",
        )

    def test_approved_legal_review_requires_known_official_source(self) -> None:
        content = (
            "## 現行制度\n\n宅地建物取引士の押印義務は2022年5月18日に廃止されました。\n\n"
            "## 注意\n\n具体的な問題文を確認します。\n\n"
            "[宅建学習](https://www.takkenai.jp/takken/)"
        )
        quality_report = self.quality.evaluate(
            title="37条書面の現行ルール",
            content=content,
            topic=self.topic,
            platform="ameba",
        )
        response = {
            "decision": "approved",
            "score": 96,
            "blocking_errors": [],
            "warnings": [],
            "verified_claims": ["押印義務の廃止日"],
            "unverifiable_claims": [],
            "source_ids": ["mlit-digital-documents-2022"],
        }
        with (
            patch("app.services.fact_review_service.settings.openai_api_key", "test-key"),
            patch.object(self.service, "_chat_json", return_value=response),
        ):
            report = self.service.review(
                title="37条書面の現行ルール",
                summary="現行ルールを確認します。",
                content=content,
                topic=self.topic,
                platform="ameba",
                quality_report=quality_report,
                attempt=0,
            )

        self.assertTrue(report.approved)
        self.assertEqual(report.source_ids, ["mlit-digital-documents-2022"])

    def test_legal_review_without_source_is_not_approved(self) -> None:
        content = "## 37条書面\n\n具体的な注意点を確認します。\n\n## 復習\n\n問題を確認します。"
        quality_report = self.quality.evaluate(
            title="37条書面の復習",
            content=content,
            topic=self.topic,
            platform="ameba",
        )
        response = {
            "decision": "approved",
            "score": 95,
            "blocking_errors": [],
            "warnings": [],
            "verified_claims": [],
            "unverifiable_claims": [],
            "source_ids": [],
        }
        with (
            patch("app.services.fact_review_service.settings.openai_api_key", "test-key"),
            patch.object(self.service, "_chat_json", return_value=response),
        ):
            report = self.service.review(
                title="37条書面の復習",
                summary="復習方法です。",
                content=content,
                topic=self.topic,
                platform="ameba",
                quality_report=quality_report,
                attempt=0,
            )

        self.assertFalse(report.approved)
        self.assertIn("Legal or regulatory content has no verified official source id.", report.blocking_errors)


if __name__ == "__main__":
    unittest.main()
