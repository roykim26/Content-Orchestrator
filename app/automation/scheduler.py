from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import Session

from app.core.config import settings
from app.db import engine
from app.services.automated_topic_service import AutomatedTopicService
from app.services.topic_refill_service import TopicRefillService

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:  # pragma: no cover - graceful fallback before dependencies are installed
    AsyncIOScheduler = None
    CronTrigger = None

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=settings.automation_timezone) if AsyncIOScheduler else None


def start_scheduler() -> None:
    if not scheduler or not CronTrigger:
        logger.warning("APScheduler is not installed; weekly topic selection scheduler is unavailable.")
        return
    if not settings.enable_topic_selection_scheduler and not settings.enable_topic_refill_scheduler:
        logger.info("Topic automation schedulers are disabled.")
        return
    if scheduler.running:
        return

    if settings.enable_topic_selection_scheduler:
        trigger = CronTrigger.from_crontab(
            settings.topic_selection_cron,
            timezone=settings.automation_timezone,
        )
        scheduler.add_job(
            run_weekly_topic_selection_job,
            trigger=trigger,
            id="weekly_topic_selection",
            replace_existing=True,
        )
        logger.info(
            "Weekly topic selection scheduler registered with cron %s (%s).",
            settings.topic_selection_cron,
            settings.automation_timezone,
        )

    if settings.enable_topic_refill_scheduler:
        refill_trigger = CronTrigger.from_crontab(
            settings.topic_refill_cron,
            timezone=settings.automation_timezone,
        )
        scheduler.add_job(
            run_topic_refill_job,
            trigger=refill_trigger,
            id="topic_inventory_refill",
            replace_existing=True,
        )
        logger.info(
            "Topic refill scheduler registered with cron %s (%s).",
            settings.topic_refill_cron,
            settings.automation_timezone,
        )

    scheduler.start()
    logger.info("Topic automation scheduler started.")


def stop_scheduler() -> None:
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


def run_weekly_topic_selection_job() -> None:
    with Session(engine) as session:
        service = AutomatedTopicService(session)
        result = service.run_weekly_selection(run_date=datetime.now(UTC))
        logger.info("Weekly topic selection finished: %s", result)


def run_topic_refill_job() -> None:
    with Session(engine) as session:
        service = TopicRefillService(session)
        result = service.run_refill(run_date=datetime.now(UTC), write_to_feishu=True)
        logger.info("Topic refill finished: %s", result)
