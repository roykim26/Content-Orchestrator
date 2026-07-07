import unittest

from sqlmodel import Session, SQLModel, create_engine

from app.models.artifact import ArtifactClaimRequest, ArtifactPublishResult, ContentArtifact
from app.services.publish_autopilot_service import PublishAutopilotService
from app.services.publisher_service import PublisherService


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

    def test_default_autopilot_lanes_follow_configured_rollout(self) -> None:
        self.assertEqual(
            PublishAutopilotService._default_lane_names(),
            ["note_a", "note_b", "ameba", "x_ta", "bluesky_ta"],
        )

    def test_future_lanes_are_registered(self) -> None:
        self.assertIn("x_ta", PublishAutopilotService.LANES)
        self.assertIn("bluesky_ta", PublishAutopilotService.LANES)
        self.assertIn("zenn", PublishAutopilotService.LANES)
        self.assertIn("hatena_a", PublishAutopilotService.LANES)
        self.assertIn("hatena_b", PublishAutopilotService.LANES)
        self.assertIn("livedoor", PublishAutopilotService.LANES)

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
