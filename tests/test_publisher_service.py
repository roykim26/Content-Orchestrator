import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.artifact import ArtifactClaimRequest, ArtifactPublishResult, ContentArtifact
from app.integrations.publisher_client import PublisherClient
from app.models.topic import Topic
from app.services.publish_autopilot_service import PublishAutopilotService
from app.services.publisher_service import PublisherService


ROOT_DIR = Path(__file__).resolve().parents[1]


class PublisherServiceTest(unittest.TestCase):
    def test_claim_request_normalizes_generic_account(self) -> None:
        payload = ArtifactClaimRequest(
            platform="X",
            consumer_name="social-worker",
            account=" ta_x ",
        )

        self.assertEqual(payload.platform, "x")
        self.assertEqual(payload.account, "ta_x")

    def test_claim_metadata_preserves_note_account_compatibility(self) -> None:
        artifact = ContentArtifact(
            id="art_test_note_a",
            topic_id="topic_test",
            task_id="task_test",
            platform="note",
            content_type="article",
            angle="test",
            content="test",
            extra_metadata={},
        )
        payload = ArtifactClaimRequest(
            platform="note",
            consumer_name="note-worker",
            account="note_a",
        )

        metadata = PublisherService._metadata_with_claim_account(artifact, payload)

        self.assertEqual(metadata["account"], "note_a")
        self.assertEqual(metadata["note_account"], "note_a")

    def test_list_publishable_artifacts_filters_generic_account(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(
                ContentArtifact(
                    id="art_x_ta",
                    topic_id="topic_test",
                    task_id="task_test_1",
                    platform="x",
                    content_type="short_post",
                    angle="test",
                    content="test",
                    status="publish_pending",
                    extra_metadata={"account": "ta_x"},
                )
            )
            session.add(
                ContentArtifact(
                    id="art_x_ep",
                    topic_id="topic_test",
                    task_id="task_test_2",
                    platform="x",
                    content_type="short_post",
                    angle="test",
                    content="test",
                    status="publish_pending",
                    extra_metadata={"account": "ep_x"},
                )
            )
            session.commit()

            artifacts = PublisherService(session).list_publishable_artifacts(
                platform="x",
                status="publish_pending",
                account="ta_x",
            )

        self.assertEqual([artifact.id for artifact in artifacts], ["art_x_ta"])

    def test_hatena_account_claim_accepts_note_account_alias(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(
                ContentArtifact(
                    id="art_hatena_note_b",
                    topic_id="topic_test",
                    task_id="task_test_1",
                    platform="hatena",
                    content_type="article",
                    angle="test",
                    content="test",
                    status="publish_pending",
                    extra_metadata={"account": "note_b", "note_account": "note_b"},
                )
            )
            session.add(
                ContentArtifact(
                    id="art_hatena_note_a",
                    topic_id="topic_test",
                    task_id="task_test_2",
                    platform="hatena",
                    content_type="article",
                    angle="test",
                    content="test",
                    status="publish_pending",
                    extra_metadata={"account": "note_a", "note_account": "note_a"},
                )
            )
            session.commit()

            artifacts = PublisherService(session).list_publishable_artifacts(
                platform="hatena",
                status="publish_pending",
                account="B",
            )

        self.assertEqual([artifact.id for artifact in artifacts], ["art_hatena_note_b"])

    def test_default_autopilot_lanes_follow_configured_rollout(self) -> None:
        self.assertEqual(
            PublishAutopilotService._default_lane_names(),
            ["note_a", "note_b", "ameba", "x_ta", "bluesky_ta", "hatena_b"],
        )

    def test_autopilot_script_all_uses_configured_lane_rollout(self) -> None:
        script = (ROOT_DIR / "scripts" / "invoke-publish-autopilot.ps1").read_text(encoding="utf-8")

        self.assertIn('"x_ta"', script)
        self.assertIn('"bluesky_ta"', script)
        self.assertIn("PUBLISH_AUTOPILOT_LANES", script)
        self.assertIn("$lanes = Get-ConfiguredAutopilotLanes", script)

    def test_future_lanes_are_registered(self) -> None:
        self.assertIn("x_ta", PublishAutopilotService.LANES)
        self.assertIn("bluesky_ta", PublishAutopilotService.LANES)
        self.assertIn("zenn", PublishAutopilotService.LANES)
        self.assertIn("hatena_a", PublishAutopilotService.LANES)
        self.assertIn("hatena_b", PublishAutopilotService.LANES)
        self.assertIn("livedoor", PublishAutopilotService.LANES)

    def test_platform_lanes_share_8221_publisher_health_label(self) -> None:
        self.assertEqual(
            PublishAutopilotService.LANES["zenn"].expected_health["app_instance_label"],
            "8221_orch_publish_platforms",
        )
        self.assertEqual(
            PublishAutopilotService.LANES["hatena_a"].expected_health["app_instance_label"],
            "8221_orch_publish_platforms",
        )

    def test_hatena_trigger_passes_lane_account(self) -> None:
        service = PublishAutopilotService.__new__(PublishAutopilotService)
        lane = PublishAutopilotService.LANES["hatena_a"]
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"status": "no_work"}
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=None)
        client.post.return_value = response

        with patch("app.services.publish_autopilot_service.httpx.Client", return_value=client):
            result = service._trigger_publisher(lane)

        client.post.assert_called_once_with(lane.trigger_url, params={"account": "A"})
        self.assertEqual(result["status"], "no_work")

    def test_hatena_lanes_match_different_topic_accounts(self) -> None:
        topic_a = Topic(
            id="topic_a",
            master_topic="A",
            topic_cluster="cluster",
            business_goal="goal",
            target_keyword="keyword",
            target_platforms=["hatena"],
            status="ready",
            note_account="note_a",
        )
        topic_b = Topic(
            id="topic_b",
            master_topic="B",
            topic_cluster="cluster",
            business_goal="goal",
            target_keyword="keyword",
            target_platforms=["hatena"],
            status="ready",
            note_account="note_b",
        )

        self.assertTrue(
            PublishAutopilotService._topic_matches_lane_account(
                topic_a,
                PublishAutopilotService.LANES["hatena_a"],
            )
        )
        self.assertFalse(
            PublishAutopilotService._topic_matches_lane_account(
                topic_b,
                PublishAutopilotService.LANES["hatena_a"],
            )
        )
        self.assertTrue(
            PublishAutopilotService._topic_matches_lane_account(
                topic_b,
                PublishAutopilotService.LANES["hatena_b"],
            )
        )

    def test_publisher_client_claim_includes_generic_account(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"artifacts": []}

        with patch("app.integrations.publisher_client.httpx.post", return_value=response) as post:
            PublisherClient(base_url="http://orchestrator").claim_artifacts(
                platform="hatena",
                consumer_name="platform-publisher",
                account="A",
            )

        self.assertEqual(post.call_args.kwargs["json"]["account"], "A")

    def test_note_b_editor_url_normalizes_to_note_b_public_slug(self) -> None:
        artifact = ContentArtifact(
            id="art_test_note_b",
            topic_id="topic_test",
            task_id="task_test",
            platform="note",
            content_type="article",
            angle="test",
            content="test",
            extra_metadata={"note_account": "note_b"},
        )
        payload = ArtifactPublishResult(
            published=True,
            published_url="https://editor.note.com/notes/n8234e7ac4f2c/edit",
        )

        normalized = PublisherService._normalize_publish_result(
            PublisherService.__new__(PublisherService),
            artifact,
            payload,
        )

        self.assertEqual(
            normalized.published_url,
            "https://note.com/yo_notebook/n/n8234e7ac4f2c",
        )

    def test_note_b_public_url_normalizes_to_note_b_public_slug(self) -> None:
        artifact = ContentArtifact(
            id="art_test_note_b",
            topic_id="topic_test",
            task_id="task_test",
            platform="note",
            content_type="article",
            angle="test",
            content="test",
            extra_metadata={"note_account": "note_b"},
        )
        payload = ArtifactPublishResult(
            published=True,
            published_url="https://note.com/good_jaguar8332/n/n54bffe8b58fd",
        )

        normalized = PublisherService._normalize_publish_result(
            PublisherService.__new__(PublisherService),
            artifact,
            payload,
        )

        self.assertEqual(
            normalized.published_url,
            "https://note.com/yo_notebook/n/n54bffe8b58fd",
        )

    def test_note_a_editor_url_normalizes_to_note_a_public_slug(self) -> None:
        artifact = ContentArtifact(
            id="art_test_note_a",
            topic_id="topic_test",
            task_id="task_test",
            platform="note",
            content_type="article",
            angle="test",
            content="test",
            extra_metadata={"note_account": "note_a"},
        )
        payload = ArtifactPublishResult(
            published=True,
            published_url="https://editor.note.com/notes/nf045396229fe/edit",
        )

        normalized = PublisherService._normalize_publish_result(
            PublisherService.__new__(PublisherService),
            artifact,
            payload,
        )

        self.assertEqual(
            normalized.published_url,
            "https://note.com/good_jaguar8332/n/nf045396229fe",
        )


if __name__ == "__main__":
    unittest.main()
