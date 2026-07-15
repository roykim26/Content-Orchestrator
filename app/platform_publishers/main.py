from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.integrations.publisher_client import PublisherClient
from app.integrations.publisher_worker import PublishOutcome
from app.platform_publishers.adapters import HatenaPublisher, ZennPublisher


DEFAULT_LEGACY_ENV_PATH = str(Path(__file__).resolve().parents[2].parent / "zenn-bot" / ".env")
DEFAULT_LOCAL_ENV_PATH = ".env"


def load_env_file(path: str, *, override: bool = False) -> bool:
    env_path = Path(path)
    if not env_path.exists():
        return False
    with env_path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if not override and key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
    return True


LOCAL_ENV_PATH = os.getenv("PLATFORM_PUBLISHER_LOCAL_ENV_PATH", DEFAULT_LOCAL_ENV_PATH).strip()
LOCAL_ENV_LOADED = load_env_file(LOCAL_ENV_PATH)
LEGACY_ENV_PATH = os.getenv("PLATFORM_PUBLISHER_ENV_PATH", DEFAULT_LEGACY_ENV_PATH).strip()
LEGACY_ENV_LOADED = load_env_file(LEGACY_ENV_PATH)
ORCHESTRATOR_BASE_URL = os.getenv("ORCHESTRATOR_BASE_URL", "http://127.0.0.1:8020").strip()
PUBLISHER_API_KEY = os.getenv("PUBLISHER_API_KEY") or None
CONSUMER_NAME = os.getenv("ORCHESTRATOR_CONSUMER_NAME", "platform-publisher-8221").strip()
APP_INSTANCE_LABEL = os.getenv("APP_INSTANCE_LABEL", "8221_orch_publish_platforms").strip()

app = FastAPI(title="Content Orchestrator Platform Publisher", version="0.1.0")


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    return {
        "status": "healthy",
        "orchestrator_mode_enabled": True,
        "app_instance_label": APP_INSTANCE_LABEL,
        "orchestrator_base_url": ORCHESTRATOR_BASE_URL,
        "orchestrator_consumer_name": CONSUMER_NAME,
        "platform_publish_mode": "publish",
        "supported_platforms": ["zenn", "hatena"],
        "local_env_path": LOCAL_ENV_PATH,
        "local_env_loaded": LOCAL_ENV_LOADED,
        "legacy_env_path": LEGACY_ENV_PATH,
        "legacy_env_loaded": LEGACY_ENV_LOADED,
    }


@app.post("/ops/zenn/run-next-ready-draft")
def run_next_zenn() -> dict[str, Any]:
    return _run_once(platform="zenn", account=None)


@app.post("/ops/hatena/run-next-ready-draft")
def run_next_hatena(account: str | None = None) -> dict[str, Any]:
    return _run_once(platform="hatena", account=account)


def _run_once(*, platform: str, account: str | None) -> dict[str, Any]:
    client = PublisherClient(base_url=ORCHESTRATOR_BASE_URL, api_key=PUBLISHER_API_KEY, timeout=60)
    claim = client.claim_artifacts(
        platform=platform,
        consumer_name=CONSUMER_NAME,
        limit=1,
        account=account,
    )
    artifacts = claim.get("artifacts") or []
    if not artifacts:
        return {"status": "no_work", "platform": platform, "account": account, "claimed_count": 0}

    artifact = artifacts[0]
    outcome = _publish(platform=platform, account=account, artifact=artifact)
    result = client.report_publish_result(
        artifact["artifact_id"],
        published=outcome.published,
        published_url=outcome.published_url,
        external_publish_id=outcome.external_publish_id,
        status=outcome.status,
        error_message=outcome.error_message,
    )
    return {
        "status": outcome.status or ("published" if outcome.published else "failed"),
        "platform": platform,
        "account": account,
        "artifact_id": artifact["artifact_id"],
        "published_url": outcome.published_url,
        "result": result,
    }


def _publish(*, platform: str, account: str | None, artifact: dict[str, Any]) -> PublishOutcome:
    if platform == "zenn":
        return ZennPublisher.from_env().publish(artifact)
    if platform == "hatena":
        return HatenaPublisher(account=account).publish(artifact)
    return PublishOutcome(False, status="failed", error_message=f"Unsupported platform: {platform}")
