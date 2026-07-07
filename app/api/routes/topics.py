from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session

from app.db import get_session
from app.models.topic import Topic, TopicCreate, TopicRead, TopicUpdate
from app.services.feishu_topic_sync_service import FeishuTopicSyncError, FeishuTopicSyncService
from app.services.topic_import_service import TopicImportService
from app.services.topic_service import TopicService

router = APIRouter()


@router.post("", response_model=TopicRead)
def create_topic(payload: TopicCreate, session: Session = Depends(get_session)) -> Topic:
    service = TopicService(session)
    return service.create_topic(payload)


@router.get("", response_model=list[TopicRead])
def list_topics(
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Topic]:
    service = TopicService(session)
    return service.list_topics(status=status)


@router.post("/import")
async def import_topics(
    file: UploadFile | None = File(default=None),
    content_text: str | None = Form(default=None),
    filename_hint: str | None = Form(default=None),
    plan: bool = Form(default=False),
    dry_run: bool = Form(default=False),
    skip_existing: bool = Form(default=False),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = TopicImportService(session)
    if file is not None:
        content = await file.read()
        return service.import_from_upload(
            filename=file.filename or "topics.csv",
            content=content,
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )
    if content_text:
        return service.import_from_text(
            filename_hint=filename_hint or "topics.csv",
            content=content_text,
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )
    raise HTTPException(status_code=400, detail="Provide either an upload file or pasted content.")


@router.post("/sync-feishu")
def sync_feishu_topics(
    plan: bool = Query(default=False),
    dry_run: bool = Query(default=False),
    skip_existing: bool = Query(default=True),
    status: str | None = Query(default="ready"),
    limit: int | None = Query(default=None, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = FeishuTopicSyncService(session)
    try:
        return service.sync(
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
            status=status,
            limit=limit,
        )
    except FeishuTopicSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{topic_id}", response_model=TopicRead)
def get_topic(topic_id: str, session: Session = Depends(get_session)) -> Topic:
    service = TopicService(session)
    topic = service.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.get("/{topic_id}/overview")
def get_topic_overview(topic_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    service = TopicService(session)
    overview = service.get_topic_overview(topic_id)
    if not overview:
        raise HTTPException(status_code=404, detail="Topic not found")
    return overview


@router.patch("/{topic_id}", response_model=TopicRead)
def update_topic(
    topic_id: str,
    payload: TopicUpdate,
    session: Session = Depends(get_session),
) -> Topic:
    service = TopicService(session)
    topic = service.update_topic(topic_id, payload)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.post("/{topic_id}/plan")
def plan_topic(topic_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
    service = TopicService(session)
    result = service.plan_topic(topic_id)
    if not result:
        raise HTTPException(status_code=404, detail="Topic not found")
    return result
