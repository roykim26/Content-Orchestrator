from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.models.distribution_task import DistributionTask, DistributionTaskRead
from app.services.task_service import TaskService

router = APIRouter()


@router.get("", response_model=list[DistributionTaskRead])
def list_tasks(
    topic_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[DistributionTask]:
    service = TaskService(session)
    return service.list_tasks(topic_id=topic_id, platform=platform, status=status)


@router.post("/{task_id}/run")
def run_task(task_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    service = TaskService(session)
    result = service.run_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.post("/{task_id}/retry")
def retry_task(task_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    service = TaskService(session)
    result = service.retry_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result
