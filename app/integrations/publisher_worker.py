from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.integrations.publisher_client import PublisherClient


@dataclass(slots=True)
class PublishOutcome:
    published: bool
    published_url: str | None = None
    external_publish_id: str | None = None
    status: str | None = None
    error_message: str | None = None


class PublisherAdapter(ABC):
    @property
    @abstractmethod
    def platform(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def publish(self, artifact: dict[str, Any]) -> PublishOutcome:
        raise NotImplementedError


@dataclass(slots=True)
class PublisherWorker:
    client: PublisherClient
    adapter: PublisherAdapter
    consumer_name: str

    def run_once(self, limit: int = 1) -> list[dict[str, Any]]:
        claimed = self.client.claim_artifacts(
            platform=self.adapter.platform,
            consumer_name=self.consumer_name,
            limit=limit,
        )
        artifacts = claimed.get("artifacts", [])
        results: list[dict[str, Any]] = []
        for artifact in artifacts:
            artifact_id = artifact["artifact_id"]
            try:
                outcome = self.adapter.publish(artifact)
                result = self.client.report_publish_result(
                    artifact_id,
                    published=outcome.published,
                    published_url=outcome.published_url,
                    external_publish_id=outcome.external_publish_id,
                    status=outcome.status,
                    error_message=outcome.error_message,
                )
                results.append(result)
            except Exception as exc:  # pragma: no cover - adapter runtime protection
                result = self.client.report_publish_result(
                    artifact_id,
                    published=False,
                    status="failed",
                    error_message=str(exc),
                )
                results.append(result)
        return results
