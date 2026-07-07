from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.distribution_task import DistributionTask
from app.models.topic import Topic
from app.services.feishu_topic_sync_service import FeishuTopicSyncError, FeishuTopicSyncService


@dataclass(frozen=True)
class PlatformTopicInventory:
    platform: str
    pending_topic_count: int
    consumed_topic_count: int
    total_topic_count: int


class TopicInventoryAlertService:
    PUBLISHABLE_TOPIC_STATUSES = {"ready", "planned"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize_by_platform(self, *, feishu_only: bool = True) -> list[PlatformTopicInventory]:
        statement = select(Topic)
        if feishu_only:
            statement = statement.where(Topic.feishu_record_id.is_not(None)).where(Topic.feishu_record_id != "")

        pending_task_platforms_by_topic = self._pending_task_platforms_by_topic()
        totals: dict[str, int] = {}
        pending: dict[str, int] = {}
        for topic in self.session.exec(statement).all():
            platforms = self._normalize_platforms(topic.target_platforms)
            topic_status = str(topic.status or "").strip().lower()
            pending_task_platforms = pending_task_platforms_by_topic.get(topic.id, set())
            for platform in platforms:
                totals[platform] = totals.get(platform, 0) + 1
                if topic_status == "ready" or (
                    topic_status in self.PUBLISHABLE_TOPIC_STATUSES and platform in pending_task_platforms
                ):
                    pending[platform] = pending.get(platform, 0) + 1

        inventories = []
        for platform in sorted(totals):
            pending_count = pending.get(platform, 0)
            total_count = totals[platform]
            inventories.append(
                PlatformTopicInventory(
                    platform=platform,
                    pending_topic_count=pending_count,
                    consumed_topic_count=max(total_count - pending_count, 0),
                    total_topic_count=total_count,
                )
            )
        return inventories

    def _pending_task_platforms_by_topic(self) -> dict[str, set[str]]:
        tasks = self.session.exec(select(DistributionTask).where(DistributionTask.status == "pending")).all()
        platforms_by_topic: dict[str, set[str]] = {}
        for task in tasks:
            topic_id = str(task.topic_id or "").strip()
            platform = str(task.platform or "").strip().lower()
            if not topic_id or not platform:
                continue
            platforms_by_topic.setdefault(topic_id, set()).add(platform)
        return platforms_by_topic

    def check_and_notify(
        self,
        *,
        threshold: int = 5,
        dry_run: bool = False,
        feishu_only: bool = True,
    ) -> dict[str, object]:
        inventories = self.summarize_by_platform(feishu_only=feishu_only)
        low_inventory = [item for item in inventories if item.pending_topic_count < threshold]
        result: dict[str, object] = {
            "threshold": threshold,
            "feishu_only": feishu_only,
            "low_inventory_count": len(low_inventory),
            "low_inventory": [self._inventory_payload(item) for item in low_inventory],
        }
        if not low_inventory:
            return {**result, "notified": False}

        text = self._build_alert_text(low_inventory, threshold=threshold)
        result["message"] = text
        if dry_run:
            return {**result, "notified": False, "dry_run": True}

        try:
            notify_result = FeishuTopicSyncService(self.session).notify_text(text)
            return {**result, "notified": True, "notify_result": notify_result}
        except FeishuTopicSyncError as exc:
            return {**result, "notified": False, "notify_error": str(exc)}

    @staticmethod
    def _normalize_platforms(value: object) -> list[str]:
        if isinstance(value, list):
            return sorted({str(item).strip().lower() for item in value if str(item).strip()})
        if value is None:
            return []
        return sorted({item.strip().lower() for item in str(value).split(",") if item.strip()})

    @staticmethod
    def _inventory_payload(item: PlatformTopicInventory) -> dict[str, object]:
        return {
            "platform": item.platform,
            "pending_topic_count": item.pending_topic_count,
            "consumed_topic_count": item.consumed_topic_count,
            "total_topic_count": item.total_topic_count,
        }

    @staticmethod
    def _build_alert_text(items: list[PlatformTopicInventory], *, threshold: int) -> str:
        lines = [
            "Content Orchestrator 主题库存告警",
            f"触发条件：待发布主题数 < {threshold}",
            "以下平台主题库存不足，请及时补充：",
        ]
        for item in items:
            lines.append(
                " | ".join(
                    [
                        f"平台：{item.platform}",
                        f"待发布主题：{item.pending_topic_count}",
                        f"已消耗主题：{item.consumed_topic_count}",
                    ]
                )
            )
        return "\n".join(lines)
