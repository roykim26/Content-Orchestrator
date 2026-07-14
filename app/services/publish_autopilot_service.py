from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
import time
from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.core.ids import generate_id
from app.models.artifact import ArtifactApiRead, ArtifactRequeueRequest, ContentArtifact
from app.models.distribution_task import DistributionTask
from app.models.publish_run import PublishRun
from app.models.topic import Topic
from app.services.artifact_service import ArtifactService
from app.services.feishu_topic_sync_service import FeishuTopicSyncError, FeishuTopicSyncService
from app.services.publisher_service import PublisherService
from app.services.task_service import TaskService
from app.services.topic_refill_service import TopicRefillService
from app.services.topic_service import TopicService


@dataclass(frozen=True)
class PublishLane:
    name: str
    platform: str
    account: str | None
    health_url: str
    trigger_url: str
    expected_health: dict[str, object]


class PublishAutopilotService:
    """Runs the generation-to-publish loop for the currently integrated lanes."""

    LANES: dict[str, PublishLane] = {
        "note_a": PublishLane(
            name="note_a",
            platform="note",
            account="note_a",
            health_url="http://127.0.0.1:8217/health",
            trigger_url="http://127.0.0.1:8217/ops/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "note_publish_mode": "publish",
                "app_instance_label": "8217_orch_publish",
            },
        ),
        "note_b": PublishLane(
            name="note_b",
            platform="note",
            account="note_b",
            health_url="http://127.0.0.1:8215/health",
            trigger_url="http://127.0.0.1:8215/ops/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "note_publish_mode": "publish",
                "app_instance_label": "8215_orch_publish_note_b",
            },
        ),
        "ameba": PublishLane(
            name="ameba",
            platform="ameba",
            account=None,
            health_url="http://127.0.0.1:8216/health",
            trigger_url="http://127.0.0.1:8216/ops/ameba/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "ameba_publish_mode": "publish",
                "app_instance_label": "8216_orch_publish_ameba",
            },
        ),
        "x_ta": PublishLane(
            name="x_ta",
            platform="x",
            account="ta_x",
            health_url="http://127.0.0.1:8000/health",
            trigger_url="http://127.0.0.1:8000/ops/x/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8000_orch_publish_social",
            },
        ),
        "bluesky_ta": PublishLane(
            name="bluesky_ta",
            platform="bluesky",
            account="ta_bsky",
            health_url="http://127.0.0.1:8000/health",
            trigger_url="http://127.0.0.1:8000/ops/bluesky/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8000_orch_publish_social",
            },
        ),
        "zenn": PublishLane(
            name="zenn",
            platform="zenn",
            account=None,
            health_url="http://127.0.0.1:8221/health",
            trigger_url="http://127.0.0.1:8221/ops/zenn/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8221_orch_publish_platforms",
            },
        ),
        "hatena_a": PublishLane(
            name="hatena_a",
            platform="hatena",
            account="A",
            health_url="http://127.0.0.1:8221/health",
            trigger_url="http://127.0.0.1:8221/ops/hatena/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8221_orch_publish_platforms",
            },
        ),
        "hatena_b": PublishLane(
            name="hatena_b",
            platform="hatena",
            account="B",
            health_url="http://127.0.0.1:8221/health",
            trigger_url="http://127.0.0.1:8221/ops/hatena/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8221_orch_publish_platforms",
            },
        ),
        "livedoor": PublishLane(
            name="livedoor",
            platform="livedoor",
            account=None,
            health_url="http://127.0.0.1:8222/health",
            trigger_url="http://127.0.0.1:8222/ops/livedoor/run-next-ready-draft",
            expected_health={
                "status": "healthy",
                "orchestrator_mode_enabled": True,
                "app_instance_label": "8222_orch_publish_livedoor",
            },
        ),
    }

    SUCCESS_STATUSES = {"published", "published_unverified", "draft_created"}
    TERMINAL_FAILURE_STATUSES = {"failed", "rejected"}

    def __init__(self, session: Session) -> None:
        self.session = session
        self.topic_service = TopicService(session)
        self.task_service = TaskService(session)
        self.artifact_service = ArtifactService(session)
        self.publisher_service = PublisherService(session)

    def run_all(
        self,
        *,
        lanes: list[str] | None = None,
        dry_run: bool = False,
        wait: bool = True,
        wait_timeout_seconds: int = 900,
        poll_interval_seconds: int = 10,
        stale_timeout_minutes: int = 45,
        running_task_timeout_minutes: int = 45,
        topic_limit: int = 200,
        max_daily_success_per_lane: int = 1,
        max_failed_publish_requeue_attempts: int = 2,
    ) -> dict[str, object]:
        lane_names = lanes or self._default_lane_names()
        results = []
        for lane_name in lane_names:
            lane = self._resolve_lane(lane_name)
            results.append(
                self.run_lane(
                    lane,
                    dry_run=dry_run,
                    wait=wait,
                    wait_timeout_seconds=wait_timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                    stale_timeout_minutes=stale_timeout_minutes,
                    running_task_timeout_minutes=running_task_timeout_minutes,
                    topic_limit=topic_limit,
                    max_daily_success_per_lane=max_daily_success_per_lane,
                    max_failed_publish_requeue_attempts=max_failed_publish_requeue_attempts,
                )
            )
        topic_inventory_refill = TopicRefillService(self.session).run_refill(
            dry_run=dry_run,
            write_to_feishu=True,
        )
        return {
            "status": "completed",
            "dry_run": dry_run,
            "wait": wait,
            "results": results,
            "topic_inventory_refill": topic_inventory_refill,
        }

    def list_runs(self, limit: int = 20, lane: str | None = None) -> list[PublishRun]:
        statement = select(PublishRun)
        if lane:
            statement = statement.where(PublishRun.lane == lane)
        statement = statement.order_by(PublishRun.started_at.desc()).limit(limit)
        return list(self.session.exec(statement).all())

    def run_lane(
        self,
        lane: PublishLane,
        *,
        dry_run: bool,
        wait: bool,
        wait_timeout_seconds: int,
        poll_interval_seconds: int,
        stale_timeout_minutes: int,
        running_task_timeout_minutes: int,
        topic_limit: int,
        max_daily_success_per_lane: int,
        max_failed_publish_requeue_attempts: int,
    ) -> dict[str, object]:
        run = PublishRun(
            id=generate_id("pub_run"),
            lane=lane.name,
            platform=lane.platform,
            account=lane.account,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        summary: dict[str, object] = {}
        try:
            active_run = self._find_active_run(lane, excluding_run_id=run.id)
            if active_run:
                self._finish_run(
                    run,
                    status="skipped",
                    stage="lane_busy",
                    summary={"active_run_id": active_run.id, "active_run_stage": active_run.stage},
                )
                return self._run_payload(run)

            success_count = self._count_today_successes(lane)
            if success_count >= max(0, max_daily_success_per_lane):
                self._finish_run(
                    run,
                    status="skipped",
                    stage="daily_quota_reached",
                    summary={
                        "success_count_today": success_count,
                        "max_daily_success_per_lane": max_daily_success_per_lane,
                    },
                )
                return self._run_payload(run)

            self._set_stage(run, "recovering")
            summary["recovered_publishing"] = len(
                self.publisher_service.recover_stale_publishing(
                    timeout_minutes=stale_timeout_minutes,
                    requested_by=f"publish_autopilot:{lane.name}",
                    dry_run=dry_run,
                )
            )
            summary["recovered_tasks"] = self._recover_stale_running_tasks(
                timeout_minutes=running_task_timeout_minutes,
                dry_run=dry_run,
            )
            summary["requeued_failed_artifacts"] = self._requeue_retryable_failed_artifacts(
                lane,
                max_attempts=max_failed_publish_requeue_attempts,
                dry_run=dry_run,
            )

            self._set_stage(run, "healthcheck")
            health = self._check_publisher_health(lane)
            summary["publisher_health"] = health

            self._set_stage(run, "ensure_queue")
            artifact = self._find_publish_pending_artifact(lane)
            if artifact is None:
                self._sync_feishu_topics(summary, topic_limit=topic_limit, dry_run=dry_run)
                artifact = self._generate_next_artifact(lane, dry_run=dry_run)

            if artifact is None:
                self._finish_run(
                    run,
                    status="skipped",
                    stage="no_work",
                    summary={
                        **summary,
                        "message": "No eligible topic or publish_pending artifact found.",
                    },
                )
                return self._run_payload(run)

            run.artifact_id = artifact.id
            run.topic_id = artifact.topic_id
            self.session.add(run)
            self.session.commit()

            if dry_run:
                self._finish_run(
                    run,
                    status="dry_run",
                    stage="ready",
                    summary={**summary, "artifact": ArtifactApiRead.from_model(artifact).model_dump(mode="json")},
                )
                return self._run_payload(run)

            self._set_stage(run, "trigger_publish")
            trigger_result = self._trigger_publisher(lane)
            summary["trigger_result"] = trigger_result

            if wait:
                self._set_stage(run, "wait_result")
                final_artifact = self._wait_for_terminal_status(
                    artifact.id,
                    timeout_seconds=max(30, wait_timeout_seconds),
                    poll_interval_seconds=max(2, poll_interval_seconds),
                )
                final_status = final_artifact.status
                summary["final_artifact"] = ArtifactApiRead.from_model(final_artifact).model_dump(mode="json")
                if final_status in self.SUCCESS_STATUSES:
                    self._finish_run(run, status="success", stage="completed", summary=summary)
                elif final_status in self.TERMINAL_FAILURE_STATUSES:
                    raise RuntimeError(f"Artifact {artifact.id} ended in status {final_status}.")
                else:
                    raise TimeoutError(f"Artifact {artifact.id} did not reach terminal status; current={final_status}.")
            else:
                self._finish_run(run, status="accepted", stage="triggered", summary=summary)

            return self._run_payload(run)
        except Exception as exc:  # noqa: BLE001
            self._finish_run(
                run,
                status="failed",
                stage=run.stage,
                error_message=str(exc),
                summary={
                    **summary,
                    **(run.summary or {}),
                    "error_type": exc.__class__.__name__,
                },
            )
            return self._run_payload(run)

    def _resolve_lane(self, lane_name: str) -> PublishLane:
        key = lane_name.strip().lower()
        if key not in self.LANES:
            raise ValueError(f"Unknown publish lane '{lane_name}'. Expected one of: {', '.join(self.LANES)}")
        return self.LANES[key]

    @classmethod
    def _default_lane_names(cls) -> list[str]:
        configured = [
            item.strip().lower()
            for item in str(settings.publish_autopilot_lanes or "").split(",")
            if item.strip()
        ]
        return configured or ["note_a", "note_b", "ameba"]

    def _find_active_run(self, lane: PublishLane, *, excluding_run_id: str) -> PublishRun | None:
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        return self.session.exec(
            select(PublishRun)
            .where(PublishRun.lane == lane.name)
            .where(PublishRun.id != excluding_run_id)
            .where(PublishRun.status == "running")
            .where(PublishRun.updated_at >= cutoff)
            .order_by(PublishRun.updated_at.desc())
        ).first()

    def _count_today_successes(self, lane: PublishLane) -> int:
        local_now = datetime.now().astimezone()
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day = local_start.astimezone(UTC)
        runs = list(
            self.session.exec(
                select(PublishRun)
                .where(PublishRun.lane == lane.name)
                .where(PublishRun.status == "success")
                .where(PublishRun.completed_at >= start_of_day)
            ).all()
        )
        return len(runs)

    def _recover_stale_running_tasks(self, *, timeout_minutes: int, dry_run: bool) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, timeout_minutes))
        tasks = list(
            self.session.exec(
                select(DistributionTask)
                .where(DistributionTask.status == "running")
                .where(DistributionTask.updated_at <= cutoff)
            ).all()
        )
        if dry_run:
            return len(tasks)
        for task in tasks:
            task.status = "pending"
            task.error_message = f"Recovered from stale running state after {timeout_minutes}m."
            task.updated_at = datetime.now(timezone.utc)
            self.session.add(task)
        if tasks:
            self.session.commit()
        return len(tasks)

    def _requeue_retryable_failed_artifacts(
        self,
        lane: PublishLane,
        *,
        max_attempts: int,
        dry_run: bool,
    ) -> int:
        if max_attempts <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        statement = (
            select(ContentArtifact)
            .where(ContentArtifact.platform == lane.platform)
            .where(ContentArtifact.status == "failed")
            .where(ContentArtifact.reviewed == True)  # noqa: E712
            .where(ContentArtifact.publish_attempts < max_attempts)
            .where(ContentArtifact.updated_at >= cutoff)
            .order_by(ContentArtifact.updated_at.asc())
        )
        artifacts = list(self.session.exec(statement).all())

        requeued = 0
        for artifact in artifacts:
            if lane.platform == "note" and lane.account:
                note_account = str(artifact.extra_metadata.get("note_account") or "").strip()
                if note_account != lane.account:
                    continue
            if dry_run:
                requeued += 1
                continue
            payload = ArtifactRequeueRequest(
                requested_by=f"publish_autopilot:{lane.name}",
                reason=(
                    "auto requeue failed publish artifact "
                    f"(attempts={artifact.publish_attempts}, max_attempts={max_attempts})"
                ),
                clear_error=True,
            )
            if self.artifact_service.requeue_artifact(artifact.id, payload):
                requeued += 1
        return requeued

    def _check_publisher_health(self, lane: PublishLane) -> dict[str, object]:
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                response = client.get(lane.health_url)
            if response.status_code >= 400:
                raise RuntimeError(f"Publisher health failed: HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Publisher for lane {lane.name} is not reachable: {exc}") from exc

        mismatches = {}
        for key, expected in lane.expected_health.items():
            actual = payload.get(key)
            if actual != expected:
                mismatches[key] = {"expected": expected, "actual": actual}
        if mismatches:
            raise RuntimeError(f"Publisher for lane {lane.name} is not in orchestrator publish mode: {mismatches}")
        return {
            "status": payload.get("status"),
            "app_instance_label": payload.get("app_instance_label"),
            "orchestrator_mode_enabled": payload.get("orchestrator_mode_enabled"),
            "orchestrator_base_url": payload.get("orchestrator_base_url"),
            "orchestrator_consumer_name": payload.get("orchestrator_consumer_name"),
            "note_publish_mode": payload.get("note_publish_mode"),
            "ameba_publish_mode": payload.get("ameba_publish_mode"),
        }

    def _sync_feishu_topics(self, summary: dict[str, object], *, topic_limit: int, dry_run: bool) -> None:
        try:
            result = FeishuTopicSyncService(self.session).sync(
                plan=False,
                dry_run=dry_run,
                skip_existing=True,
                status="ready",
                limit=topic_limit,
            )
            summary["feishu_sync"] = result
        except FeishuTopicSyncError as exc:
            summary["feishu_sync_error"] = str(exc)

    def _generate_next_artifact(self, lane: PublishLane, *, dry_run: bool) -> ContentArtifact | None:
        topics = self._eligible_topics(lane)
        for topic in topics:
            task = self._find_pending_task(topic.id, lane.platform)
            if dry_run:
                if task is None and topic.status != "ready":
                    continue
                return ContentArtifact(
                    id="dry_run",
                    topic_id=topic.id,
                    task_id=task.id if task else "dry_run_plan",
                    platform=lane.platform,
                    content_type=task.content_type if task else "article",
                    angle=task.angle if task else "",
                    content="",
                    status="dry_run",
                    extra_metadata={
                        "would_plan_topic": topic.status == "ready" and task is None,
                        "would_run_task": task.id if task else "",
                    },
                )

            if topic.status == "ready":
                self.topic_service.plan_topic(topic.id)
                self.session.refresh(topic)
            task = self._find_pending_task(topic.id, lane.platform)
            if not task:
                continue

            result = self.task_service.run_task(task.id)
            artifact_id = str((result or {}).get("artifact_id") or "")
            if not artifact_id:
                continue
            artifact = self.artifact_service.get_artifact(artifact_id)
            if not artifact:
                continue
            if artifact.status == "review_pending" or self.artifact_service.requires_manual_review(artifact):
                if artifact.status != "review_pending":
                    self.artifact_service.defer_for_review(
                        artifact,
                        "Manual review required by product/editorial policy.",
                    )
                continue
            if artifact.status != "publish_pending":
                artifact = self.artifact_service.approve_artifact(artifact.id)
            if artifact and artifact.status == "publish_pending":
                self._assign_lane_account(artifact, lane)
                return artifact
        return None

    def _assign_lane_account(self, artifact: ContentArtifact, lane: PublishLane) -> None:
        if not lane.account:
            return
        metadata = dict(artifact.extra_metadata)
        metadata["account"] = lane.account
        if lane.platform == "note":
            metadata["note_account"] = lane.account
        elif lane.platform == "hatena":
            note_account = self._hatena_note_account(lane.account)
            if note_account:
                metadata["note_account"] = note_account
        artifact.extra_metadata = metadata
        artifact.updated_at = datetime.now(timezone.utc)
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)

    def _eligible_topics(self, lane: PublishLane) -> list[Topic]:
        topics = list(
            self.session.exec(
                select(Topic)
                .where(Topic.status.in_(["ready", "planned"]))
                .order_by(Topic.created_at.asc())
            ).all()
        )
        eligible = []
        for topic in topics:
            if lane.platform not in topic.target_platforms:
                continue
            if lane.platform == "note" and lane.account and topic.note_account != lane.account:
                continue
            if lane.platform == "hatena" and lane.account and not self._topic_matches_lane_account(topic, lane):
                continue
            eligible.append(topic)
        active_clusters = self._active_topic_clusters()
        if active_clusters:
            eligible.sort(
                key=lambda topic: (
                    0 if topic.topic_cluster.strip().lower() in active_clusters else 1,
                    topic.created_at,
                )
            )
        return eligible

    @staticmethod
    def _active_topic_clusters() -> set[str]:
        return {
            item.strip().lower()
            for item in str(settings.active_topic_clusters or "").split(",")
            if item.strip()
        }

    def _find_pending_task(self, topic_id: str, platform: str) -> DistributionTask | None:
        return self.session.exec(
            select(DistributionTask)
            .where(DistributionTask.topic_id == topic_id)
            .where(DistributionTask.platform == platform)
            .where(DistributionTask.status == "pending")
            .order_by(DistributionTask.created_at.asc())
        ).first()

    def _find_publish_pending_artifact(self, lane: PublishLane) -> ContentArtifact | None:
        statement = (
            select(ContentArtifact)
            .where(ContentArtifact.platform == lane.platform)
            .where(ContentArtifact.status == "publish_pending")
            .order_by(ContentArtifact.created_at.asc())
        )
        artifacts = list(self.session.exec(statement).all())
        active_clusters = self._active_topic_clusters()
        if active_clusters:
            artifacts.sort(
                key=lambda artifact: (
                    0
                    if str(artifact.extra_metadata.get("topic_cluster") or "").strip().lower() in active_clusters
                    else 1,
                    artifact.created_at,
                )
            )
        for artifact in artifacts:
            if lane.account:
                if not self._artifact_matches_lane_account(artifact, lane):
                    continue
            if self.artifact_service.requires_manual_review(artifact):
                self.artifact_service.defer_for_review(
                    artifact,
                    "Manual review required by product/editorial policy.",
                )
                continue
            return artifact
        return None

    @classmethod
    def _artifact_matches_lane_account(cls, artifact: ContentArtifact, lane: PublishLane) -> bool:
        aliases = set(cls._lane_account_aliases(lane))
        if not aliases:
            return True
        account_values = {str(artifact.extra_metadata.get("account") or "").strip()}
        if lane.platform in {"note", "hatena"}:
            account_values.add(str(artifact.extra_metadata.get("note_account") or "").strip())
        return bool(aliases.intersection(account_values))

    @classmethod
    def _topic_matches_lane_account(cls, topic: Topic, lane: PublishLane) -> bool:
        aliases = set(cls._lane_account_aliases(lane))
        if not aliases:
            return True
        return str(topic.note_account or "").strip() in aliases

    @classmethod
    def _lane_account_aliases(cls, lane: PublishLane) -> list[str]:
        account = str(lane.account or "").strip()
        if not account:
            return []
        aliases = [account]
        if lane.platform == "hatena":
            note_account = cls._hatena_note_account(account)
            if note_account:
                aliases.append(note_account)
        return aliases

    @staticmethod
    def _hatena_note_account(account: str | None) -> str:
        return {
            "A": "note_a",
            "B": "note_b",
            "note_a": "note_a",
            "note_b": "note_b",
        }.get(str(account or "").strip(), "")

    def _trigger_publisher(self, lane: PublishLane) -> dict[str, object]:
        params = {"account": lane.account} if lane.account and lane.platform in {"hatena"} else None
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(lane.trigger_url, params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Publisher trigger failed: HTTP {response.status_code}: {response.text}")
        payload = response.json()
        if payload.get("ok") is False:
            raise RuntimeError(f"Publisher trigger returned ok=false: {payload}")
        return dict(payload)

    def _wait_for_terminal_status(
        self,
        artifact_id: str,
        *,
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> ContentArtifact:
        deadline = time.monotonic() + timeout_seconds
        artifact = self.artifact_service.get_artifact(artifact_id)
        if not artifact:
            raise RuntimeError(f"Artifact {artifact_id} disappeared while waiting for publish result.")

        while time.monotonic() < deadline:
            self.session.expire_all()
            artifact = self.artifact_service.get_artifact(artifact_id)
            if not artifact:
                raise RuntimeError(f"Artifact {artifact_id} disappeared while waiting for publish result.")
            if artifact.status in self.SUCCESS_STATUSES | self.TERMINAL_FAILURE_STATUSES:
                return artifact
            time.sleep(poll_interval_seconds)
        self.session.expire_all()
        artifact = self.artifact_service.get_artifact(artifact_id)
        if not artifact:
            raise RuntimeError(f"Artifact {artifact_id} disappeared while waiting for publish result.")
        return artifact

    def _set_stage(self, run: PublishRun, stage: str) -> None:
        run.stage = stage
        run.updated_at = datetime.now(timezone.utc)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

    def _finish_run(
        self,
        run: PublishRun,
        *,
        status: str,
        stage: str,
        summary: dict[str, object],
        error_message: str | None = None,
    ) -> None:
        run.status = status
        run.stage = stage
        run.summary = summary
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        run.updated_at = datetime.now(timezone.utc)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

    @staticmethod
    def _run_payload(run: PublishRun) -> dict[str, object]:
        return {
            "run_id": run.id,
            "lane": run.lane,
            "platform": run.platform,
            "account": run.account,
            "status": run.status,
            "stage": run.stage,
            "artifact_id": run.artifact_id,
            "topic_id": run.topic_id,
            "error_message": run.error_message,
            "summary": run.summary,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
