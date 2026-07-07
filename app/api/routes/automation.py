from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.feedback.service import TopicFeedbackService
from app.models.automation_run import AutomationRunRead
from app.models.publish_run import PublishRunRead
from app.signals.service import TopicSignalService
from app.services.automated_topic_service import AutomatedTopicService
from app.services.publish_autopilot_service import PublishAutopilotService
from app.services.topic_inventory_alert_service import TopicInventoryAlertService
from app.services.topic_refill_service import TopicRefillService

router = APIRouter()


@router.post("/topic-selection/run")
def run_topic_selection(
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = AutomatedTopicService(session)
    return service.run_weekly_selection(force=force)


@router.get("/topic-selection/runs", response_model=list[AutomationRunRead])
def list_topic_selection_runs(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[AutomationRunRead]:
    service = AutomatedTopicService(session)
    return service.list_runs(limit=limit)


@router.post("/topic-refill/run")
def run_topic_refill(
    dry_run: bool = Query(default=False),
    force: bool = Query(default=False),
    write_to_feishu: bool = Query(default=True),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = TopicRefillService(session)
    return service.run_refill(dry_run=dry_run, force=force, write_to_feishu=write_to_feishu)


@router.get("/topic-refill/runs", response_model=list[AutomationRunRead])
def list_topic_refill_runs(
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[AutomationRunRead]:
    service = TopicRefillService(session)
    return service.list_runs(limit=limit)


@router.get("/topic-selection/signals")
def list_topic_selection_signals(
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = TopicSignalService(session)
    signals = service.list_signals()
    return {
        "count": len(signals),
        "signals": [
            {
                "keyword": signal.keyword,
                "source_name": signal.source_name,
                "source_type": signal.source_type,
                "score": signal.score,
                "topic_cluster": signal.topic_cluster,
                "business_goal": signal.business_goal,
                "priority": signal.priority,
                "target_platforms": signal.target_platforms,
                "metadata": signal.metadata,
            }
            for signal in signals
        ],
        "sources": service.preview_strategy_keywords(),
    }


@router.get("/topic-selection/feedback")
def get_topic_selection_feedback(
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = TopicFeedbackService(session)
    return service.summarize()


@router.post("/topic-inventory-alert/check")
def check_topic_inventory_alert(
    dry_run: bool = Query(default=False),
    threshold: int = Query(default=5, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = TopicInventoryAlertService(session)
    return service.check_and_notify(threshold=threshold, dry_run=dry_run, feishu_only=True)


@router.post("/publish-autopilot/run")
def run_publish_autopilot(
    lanes: list[str] | None = Query(default=None),
    dry_run: bool = Query(default=False),
    wait: bool = Query(default=True),
    wait_timeout_seconds: int = Query(default=900, ge=30, le=3600),
    poll_interval_seconds: int = Query(default=10, ge=2, le=60),
    stale_timeout_minutes: int = Query(default=45, ge=1, le=1440),
    running_task_timeout_minutes: int = Query(default=45, ge=1, le=1440),
    topic_limit: int = Query(default=200, ge=1, le=500),
    max_daily_success_per_lane: int = Query(default=1, ge=0, le=10),
    max_failed_publish_requeue_attempts: int = Query(default=2, ge=0, le=10),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = PublishAutopilotService(session)
    return service.run_all(
        lanes=lanes,
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


@router.get("/publish-autopilot/runs", response_model=list[PublishRunRead])
def list_publish_autopilot_runs(
    limit: int = Query(default=20, ge=1, le=100),
    lane: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[PublishRunRead]:
    service = PublishAutopilotService(session)
    return service.list_runs(limit=limit, lane=lane)
