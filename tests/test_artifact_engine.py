from __future__ import annotations

import unittest
import json
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.engines.artifact_engine import ArtifactEngine
from app.core.config import settings
from app.models.artifact import ArtifactClaimRequest, ArtifactGenerationPayload, ContentArtifact
from app.models.topic import Topic
from app.services.publisher_service import PublisherService


class ArtifactEngineTargetLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ArtifactEngine()
        self.topic = Topic(
            id="topic_ukamiru",
            master_topic="資格試験の学習方法",
            topic_cluster="exam_study",
            business_goal="traffic_reach",
            target_keyword="資格試験 問題演習",
            priority="A",
            target_url="https://ukamiru.jp/",
            brand_name="Ukamiru",
        )

    @staticmethod
    def _payload(platform: str) -> ArtifactGenerationPayload:
        return ArtifactGenerationPayload(
            task_id=f"task_{platform}",
            platform=platform,
            content_type="article" if platform in {"hatena", "zenn"} else "short_post",
            objective="traffic_reach",
            angle="practical",
        )

    def test_hatena_and_zenn_receive_one_tracked_markdown_link(self) -> None:
        result = ("十分な長さのテストタイトル", "十分な長さの編集用サマリーです。", "Ukamiruで学習を整理します。")

        for platform in ("hatena", "zenn"):
            with self.subTest(platform=platform):
                _, _, content = self.engine._postprocess_generated_result(
                    result,
                    self._payload(platform),
                    self.topic,
                )
                expected = (
                    f"https://www.ukamiru.jp/?utm_source={platform}"
                    "&utm_medium=referral&utm_campaign=traffic_reach&utm_content=topic_ukamiru"
                )
                self.assertEqual(content.count(expected), 1)
                self.assertIn(f"]({expected})", content)

    def test_x_and_bluesky_receive_one_tracked_raw_url(self) -> None:
        result = ("十分な長さのテストタイトル", "編集用サマリー", "今日の問題演習を振り返り、弱点を一つだけ整理してみましょう。")

        for platform, max_length in (("x", 260), ("bluesky", 300)):
            with self.subTest(platform=platform):
                _, _, content = self.engine._postprocess_generated_result(
                    result,
                    self._payload(platform),
                    self.topic,
                )
                expected = (
                    f"https://www.ukamiru.jp/?utm_source={platform}"
                    "&utm_medium=referral&utm_campaign=traffic_reach&utm_content=topic_ukamiru"
                )
                self.assertEqual(content.count(expected), 1)
                self.assertTrue(content.endswith(expected))
                self.assertLessEqual(len(content), max_length)

    def test_social_post_replaces_existing_target_url_without_duplication(self) -> None:
        result = (
            "十分な長さのテストタイトル",
            "編集用サマリー",
            "詳しくはこちら https://ukamiru.jp/?utm_source=old",
        )

        _, _, content = self.engine._postprocess_generated_result(result, self._payload("x"), self.topic)

        self.assertNotIn("utm_source=old", content)
        self.assertEqual(content.count("https://www.ukamiru.jp/?utm_source=x"), 1)

    def test_tracking_preserves_existing_query_parameters(self) -> None:
        tracked = self.engine._build_tracked_target_url(
            target_url="https://ukamiru.jp/start?campaign=summer&utm_source=old",
            platform="hatena",
        )

        self.assertEqual(
            tracked,
            "https://ukamiru.jp/start?campaign=summer&utm_source=hatena&utm_medium=referral",
        )

    def test_claim_backfills_link_for_existing_unlinked_draft(self) -> None:
        database = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(database)
        with Session(database) as session:
            session.add(self.topic)
            session.add(
                ContentArtifact(
                    id="artifact_existing_zenn",
                    topic_id=self.topic.id,
                    task_id="task_existing_zenn",
                    platform="zenn",
                    content_type="technical_article",
                    angle="implementation",
                    artifact_title="既存の十分な長さのタイトル",
                    artifact_summary="既存草稿を公開前に補正するための十分な長さの要約です。",
                    content=(
                        "## 設計上の判断\n\n"
                        "Ukamiruの復習導線を具体的なデータ設計から解説します。\n\n"
                        "## 実装例\n\n選択肢ごとの状態を保存する例を示します。\n\n"
                        "## 注意点\n\n弱点バンクと模試の責務を分けます。"
                    ),
                    status="publish_pending",
                    reviewed=True,
                    reviewed_by="test-editor",
                )
            )
            session.commit()

            artifacts = PublisherService(session).claim_artifacts(
                ArtifactClaimRequest(
                    platform="zenn",
                    consumer_name="publisher-test",
                    limit=1,
                )
            )

            self.assertEqual(len(artifacts), 1)
            self.assertIn(
                "](https://www.ukamiru.jp/?utm_source=zenn",
                artifacts[0].content,
            )

    def test_ameba_uses_platform_prompt_path_instead_of_legacy_generator(self) -> None:
        content = (
            "学習場面を具体的に整理します。\n\n"
            "## 朝の問題演習\n\n選択肢の理由まで確認します。" + "理解を積み上げます。" * 25 + "\n\n"
            "## 夜の弱点復習\n\n弱点バンクで復習します。" + "間違いを整理します。" * 25 + "\n\n"
            "## 週末の確認\n\n模試で仕上がりを確認します。" + "次の行動を決めます。" * 25
        )
        response = json.dumps(
            {
                "title": "毎日の問題演習を続ける学習例",
                "summary": "朝・夜・週末に分けて問題演習と弱点復習を続ける具体例を紹介します。",
                "content": content,
            },
            ensure_ascii=False,
        )
        payload = self._payload("ameba").model_copy(
            update={"content_type": "article", "extra_metadata": {"system_prompt": "AMEBA V2"}}
        )

        with (
            patch.object(settings, "openai_api_key", "test-key"),
            patch.object(self.engine, "_chat_completion", return_value=response) as chat,
            patch.object(
                self.engine,
                "_generate_legacy_article",
                side_effect=AssertionError("legacy generator must not be used"),
            ),
        ):
            title, _, generated = self.engine.generate(payload, self.topic)

        self.assertEqual(title, "毎日の問題演習を続ける学習例")
        self.assertIn("utm_source=ameba", generated)
        self.assertEqual(chat.call_args.kwargs["system_prompt"], "AMEBA V2")


if __name__ == "__main__":
    unittest.main()
