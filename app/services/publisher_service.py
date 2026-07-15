import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, or_
from sqlmodel import Session, select

from app.core.exceptions import InvalidStateError
from app.engines.artifact_engine import ArtifactEngine
from app.models.artifact import ArtifactClaimRequest, ArtifactGenerationPayload, ArtifactPublishResult, ContentArtifact
from app.models.topic import Topic
from app.services.feishu_topic_sync_service import FeishuTopicSyncService
from app.services.artifact_service import ArtifactService


NOTE_PUBLIC_SLUGS_BY_ACCOUNT = {
    "note_a": "good_jaguar8332",
    "note_b": "yo_notebook",
}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PublisherService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_publishable_artifacts(
        self,
        platform: str,
        status: str,
        account: str | None = None,
        note_account: str | None = None,
    ) -> list[ContentArtifact]:
        statement = (
            select(ContentArtifact)
            .where(ContentArtifact.platform == platform.lower())
            .where(ContentArtifact.status == status)
        )
        statement = self._apply_account_filter(
            statement,
            platform=platform,
            account=account,
            note_account=note_account,
        )
        return list(self.session.exec(statement.order_by(ContentArtifact.created_at.asc())).all())

    def claim_artifacts(self, payload: ArtifactClaimRequest) -> list[ContentArtifact]:
        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        if dialect_name == "sqlite":
            # SQLite has no row-level locking, so take a short write lock
            # before selecting claimable artifacts to avoid double-claim races.
            self.session.connection().exec_driver_sql("BEGIN IMMEDIATE")

        statement = (
            select(ContentArtifact)
            .where(ContentArtifact.platform == payload.platform)
            .where(ContentArtifact.status == "publish_pending")
        )
        statement = self._apply_account_filter(
            statement,
            platform=payload.platform,
            account=payload.account,
            note_account=payload.note_account,
        )
        statement = statement.order_by(ContentArtifact.created_at.asc()).limit(payload.limit)
        if dialect_name != "sqlite":
            statement = statement.with_for_update(skip_locked=True)

        artifacts = list(self.session.exec(statement).all())
        if payload.dry_run:
            return artifacts

        now = datetime.now(timezone.utc)
        claimable: list[ContentArtifact] = []
        artifact_service = ArtifactService(self.session)
        for artifact in artifacts:
            if not artifact.reviewed:
                artifact.status = "review_pending"
                artifact.review_notes = "Artifact reached publish_pending without an editorial review."
                self.session.add(artifact)
                continue
            if (
                artifact_service.requires_manual_review(artifact)
                and not artifact_service.has_trusted_fact_review(artifact)
            ):
                artifact.status = "review_pending"
                artifact.reviewed = False
                artifact.reviewed_by = None
                artifact.review_notes = "Trusted fact review is required by product/content policy."
                self.session.add(artifact)
                continue
            self._ensure_target_link_before_publish(artifact)
            try:
                artifact_service._validate_publish_ready(artifact, automated=False)
            except InvalidStateError as exc:
                artifact.status = "review_pending"
                artifact.reviewed = False
                artifact.reviewed_by = None
                artifact.review_notes = str(exc)
                self.session.add(artifact)
                continue
            artifact.status = "publishing"
            artifact.claimed_by = payload.consumer_name
            artifact.extra_metadata = self._metadata_with_claim_account(artifact, payload)
            artifact.publish_started_at = now
            artifact.publish_attempts += 1
            artifact.updated_at = now
            self.session.add(artifact)
            claimable.append(artifact)
        self.session.commit()
        for artifact in claimable:
            self.session.refresh(artifact)
        return claimable

    def _ensure_target_link_before_publish(self, artifact: ContentArtifact) -> None:
        if artifact.platform not in {"ameba", "hatena", "livedoor", "note", "zenn", "x", "bluesky"}:
            return
        topic = self.session.get(Topic, artifact.topic_id)
        if not topic:
            return
        payload = ArtifactGenerationPayload(
            task_id=artifact.task_id,
            platform=artifact.platform,
            content_type=artifact.content_type,
            objective=str(artifact.extra_metadata.get("objective") or topic.business_goal),
            angle=artifact.angle,
            extra_metadata=dict(artifact.extra_metadata),
        )
        _, _, content = ArtifactEngine()._postprocess_generated_result(
            (
                artifact.artifact_title or topic.master_topic,
                artifact.artifact_summary or "",
                artifact.content,
            ),
            payload,
            topic,
        )
        artifact.content = content

    @staticmethod
    def _claim_account(payload: ArtifactClaimRequest) -> str | None:
        return payload.account or payload.note_account

    @classmethod
    def _metadata_with_claim_account(
        cls,
        artifact: ContentArtifact,
        payload: ArtifactClaimRequest,
    ) -> dict[str, object]:
        account = cls._claim_account(payload)
        metadata = dict(artifact.extra_metadata)
        if account:
            metadata["account"] = account
        if payload.note_account:
            metadata["note_account"] = payload.note_account
        elif artifact.platform == "note" and account:
            metadata["note_account"] = account
        return metadata

    @staticmethod
    def _apply_account_filter(statement, *, platform: str, account: str | None, note_account: str | None):
        account_key = str(account or note_account or "").strip()
        if not account_key:
            return statement
        aliases = PublisherService._account_aliases(platform, account_key)
        if platform.lower() == "note":
            conditions = [
                cast(ContentArtifact.extra_metadata["note_account"], String) == f'"{alias}"'
                for alias in aliases
            ]
        elif platform.lower() == "hatena":
            conditions = []
            for alias in aliases:
                conditions.extend(
                    [
                        cast(ContentArtifact.extra_metadata["account"], String) == f'"{alias}"',
                        cast(ContentArtifact.extra_metadata["note_account"], String) == f'"{alias}"',
                    ]
                )
        else:
            conditions = [
                cast(ContentArtifact.extra_metadata["account"], String) == f'"{alias}"'
                for alias in aliases
            ]
        return statement.where(or_(*conditions))

    @staticmethod
    def _account_aliases(platform: str, account_key: str) -> list[str]:
        aliases = [account_key]
        if platform.lower() == "hatena":
            mapping = {
                "A": "note_a",
                "B": "note_b",
                "note_a": "A",
                "note_b": "B",
            }
            mapped = mapping.get(account_key)
            if mapped:
                aliases.append(mapped)
        return aliases

    def write_publish_result(
        self,
        artifact_id: str,
        payload: ArtifactPublishResult,
    ) -> ContentArtifact | None:
        artifact = self.session.get(ContentArtifact, artifact_id)
        if not artifact:
            return None
        payload = self._normalize_publish_result(artifact, payload)
        is_draft_result = (payload.status or "").strip().lower() == "draft_created"
        is_success_result = payload.published or is_draft_result
        if artifact.status not in {
            "publish_pending",
            "publishing",
            "draft_created",
            "failed",
            "published_unverified",
        } and is_success_result:
            raise InvalidStateError(
                f"Artifact in status '{artifact.status}' cannot be marked as {payload.status!r}."
            )
        artifact.published = payload.published
        artifact.published_url = payload.published_url
        artifact.external_publish_id = payload.external_publish_id
        artifact.status = payload.status if is_success_result else "failed"
        if is_success_result:
            artifact.claimed_by = None
        else:
            artifact.claimed_by = None
        if payload.error_message:
            artifact.review_notes = payload.error_message
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        self._write_feishu_publish_result(artifact, payload)
        self._notify_feishu_publish_result(artifact, payload)
        return artifact

    def _normalize_publish_result(
        self,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> ArtifactPublishResult:
        if artifact.platform == "bluesky" and payload.published:
            published_url = (payload.published_url or "").strip()
            public_url = self._canonical_public_bluesky_url(published_url)
            if public_url:
                return ArtifactPublishResult(
                    published=True,
                    published_url=public_url,
                    external_publish_id=payload.external_publish_id,
                    status=payload.status,
                    error_message=payload.error_message,
                )

        if artifact.platform != "note" or not payload.published:
            return payload

        published_url = (payload.published_url or "").strip()
        public_url = self._canonical_public_note_url(artifact, published_url)
        if public_url:
            return ArtifactPublishResult(
                published=True,
                published_url=public_url,
                external_publish_id=payload.external_publish_id,
                status=payload.status,
                error_message=payload.error_message,
            )

        if not self._is_note_editor_url(published_url):
            return payload

        detail = (
            "note publish was not confirmed because publisher returned an editor URL "
            f"instead of a public note URL: {published_url}"
        )
        error_message = " | ".join(part for part in [payload.error_message, detail] if part)
        return ArtifactPublishResult(
            published=False,
            published_url=None,
            external_publish_id=payload.external_publish_id,
            status="failed",
            error_message=error_message,
        )

    @staticmethod
    def _is_note_editor_url(url: str) -> bool:
        return "editor.note.com" in url or "/publish/" in url or "/edit/" in url

    @staticmethod
    def _canonical_public_bluesky_url(url: str) -> str | None:
        match = re.fullmatch(
            r"at://([^/]+)/app\.bsky\.feed\.post/([^/?#]+)",
            url,
        )
        if not match:
            return None
        return f"https://bsky.app/profile/{match.group(1)}/post/{match.group(2)}"

    @staticmethod
    def _canonical_public_note_url(artifact: ContentArtifact, url: str) -> str | None:
        note_account = artifact.extra_metadata.get("note_account")
        slug = NOTE_PUBLIC_SLUGS_BY_ACCOUNT.get(str(note_account or ""))
        if not slug:
            return None

        match = re.search(r"/notes/([^/?#]+)", url) or re.search(r"note\.com/[^/?#]+/n/([^/?#]+)", url)
        if not match:
            return None
        return f"https://note.com/{slug}/n/{match.group(1)}"

    def _write_feishu_publish_result(
        self,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> None:
        if artifact.platform not in {"note", "ameba"}:
            return

        topic = self.session.get(Topic, artifact.topic_id)
        if not topic or not topic.feishu_record_id:
            return

        now = datetime.now(timezone.utc)
        try:
            sync_service = FeishuTopicSyncService(self.session)
            if artifact.platform == "ameba":
                try:
                    result = sync_service.write_ameba_publish_result(
                        topic=topic,
                        artifact=artifact,
                        payload=payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    if "RecordIdNotFound" not in str(exc):
                        raise
                    result = sync_service.write_legacy_ameba_publish_result(
                        topic=topic,
                        artifact=artifact,
                        payload=payload,
                    )
            else:
                try:
                    result = sync_service.write_note_publish_result(
                        topic=topic,
                        artifact=artifact,
                        payload=payload,
                    )
                except Exception as exc:  # noqa: BLE001
                    if "RecordIdNotFound" not in str(exc):
                        raise
                    result = sync_service.write_legacy_note_publish_result(
                        topic=topic,
                        artifact=artifact,
                        payload=payload,
                    )
            metadata = dict(artifact.extra_metadata)
            metadata.pop("feishu_writeback_error", None)
            metadata.pop("feishu_writeback_failed_at", None)
            artifact.extra_metadata = {
                **metadata,
                "feishu_writeback_at": now.isoformat(),
                "feishu_writeback_record_id": result.get("record_id", ""),
                "feishu_writeback_fields": result.get("written_fields", []),
                "feishu_writeback_table": result.get("table", "topic_sync"),
            }
        except Exception as exc:  # noqa: BLE001
            artifact.extra_metadata = {
                **artifact.extra_metadata,
                "feishu_writeback_error": str(exc),
                "feishu_writeback_failed_at": now.isoformat(),
            }
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)

    def _notify_feishu_publish_result(
        self,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> None:
        if not (payload.published or (payload.status or "").strip().lower() in {"draft_created", "published_unverified"}):
            return

        topic = self.session.get(Topic, artifact.topic_id)
        if not topic:
            return

        now = datetime.now(timezone.utc)
        try:
            result = FeishuTopicSyncService(self.session).notify_publish_result(
                topic=topic,
                artifact=artifact,
                payload=payload,
            )
            metadata = dict(artifact.extra_metadata)
            metadata.pop("feishu_notify_error", None)
            metadata.pop("feishu_notify_failed_at", None)
            artifact.extra_metadata = {
                **metadata,
                "feishu_notify_at": now.isoformat(),
                "feishu_notify_message_id": result.get("message_id", ""),
            }
        except Exception as exc:  # noqa: BLE001
            artifact.extra_metadata = {
                **artifact.extra_metadata,
                "feishu_notify_error": str(exc),
                "feishu_notify_failed_at": now.isoformat(),
            }
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)

    def recover_stale_publishing(
        self,
        *,
        timeout_minutes: int,
        requested_by: str | None = None,
        artifact_id: str | None = None,
        dry_run: bool = False,
    ) -> list[ContentArtifact]:
        timeout_minutes = max(1, timeout_minutes)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        statement = select(ContentArtifact).where(ContentArtifact.status == "publishing")
        if artifact_id:
            statement = statement.where(ContentArtifact.id == artifact_id)

        artifacts = list(self.session.exec(statement.order_by(ContentArtifact.publish_started_at.asc())).all())
        stale_artifacts: list[ContentArtifact] = []
        now = datetime.now(timezone.utc)

        for artifact in artifacts:
            started_at = _as_utc(artifact.publish_started_at or artifact.updated_at)
            if started_at is None or started_at > cutoff:
                continue

            stale_artifacts.append(artifact)
            if dry_run:
                continue

            note_parts = [
                f"stale publishing recovered after {timeout_minutes}m",
            ]
            if requested_by:
                note_parts.append(f"requested_by={requested_by}")

            artifact.extra_metadata = {
                **artifact.extra_metadata,
                "last_publish_recovery_note": " | ".join(note_parts),
                "last_publish_recovery_at": now.isoformat(),
                "last_publish_recovery_claimed_by": artifact.claimed_by,
                "last_publish_recovery_started_at": (
                    artifact.publish_started_at.isoformat() if artifact.publish_started_at else ""
                ),
            }
            artifact.claimed_by = None
            artifact.publish_started_at = None
            artifact.status = "publish_pending"
            artifact.updated_at = now
            self.session.add(artifact)

        if stale_artifacts and not dry_run:
            self.session.commit()
            for artifact in stale_artifacts:
                self.session.refresh(artifact)

        return stale_artifacts
