from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class PublisherClient:
    base_url: str
    timeout: float = 30.0
    api_key: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def claim_artifacts(self, platform: str, consumer_name: str, limit: int = 1) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url.rstrip('/')}/publisher/claims",
            json={
                "platform": platform,
                "consumer_name": consumer_name,
                "limit": limit,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def report_publish_result(
        self,
        artifact_id: str,
        *,
        published: bool,
        published_url: str | None = None,
        external_publish_id: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "published": published,
            "published_url": published_url,
            "external_publish_id": external_publish_id,
            "status": status or ("published" if published else "failed"),
            "error_message": error_message,
        }
        response = httpx.post(
            f"{self.base_url.rstrip('/')}/publisher/artifacts/{artifact_id}/publish-result",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
