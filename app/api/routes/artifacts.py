from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.models.artifact import (
    ArtifactApiRead,
    ArtifactPerformanceUpdate,
    ArtifactRequeueRequest,
    ArtifactReviewRequest,
)
from app.services.artifact_service import ArtifactService

router = APIRouter()


@router.get("", response_model=list[ArtifactApiRead])
def list_artifacts(
    topic_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[ArtifactApiRead]:
    service = ArtifactService(session)
    artifacts = service.list_artifacts(topic_id=topic_id, platform=platform, status=status)
    return [ArtifactApiRead.from_model(artifact) for artifact in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactApiRead)
def get_artifact(artifact_id: str, session: Session = Depends(get_session)) -> ArtifactApiRead:
    service = ArtifactService(session)
    artifact = service.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)


@router.patch("/{artifact_id}/review", response_model=ArtifactApiRead)
def review_artifact(
    artifact_id: str,
    payload: ArtifactReviewRequest,
    session: Session = Depends(get_session),
) -> ArtifactApiRead:
    service = ArtifactService(session)
    artifact = service.review_artifact(artifact_id, payload)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)


@router.post("/{artifact_id}/approve", response_model=ArtifactApiRead)
def approve_artifact(artifact_id: str, session: Session = Depends(get_session)) -> ArtifactApiRead:
    service = ArtifactService(session)
    artifact = service.approve_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)


@router.post("/{artifact_id}/requeue", response_model=ArtifactApiRead)
def requeue_artifact(
    artifact_id: str,
    payload: ArtifactRequeueRequest,
    session: Session = Depends(get_session),
) -> ArtifactApiRead:
    service = ArtifactService(session)
    artifact = service.requeue_artifact(artifact_id, payload)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)


@router.post("/{artifact_id}/performance", response_model=ArtifactApiRead)
def update_artifact_performance(
    artifact_id: str,
    payload: ArtifactPerformanceUpdate,
    session: Session = Depends(get_session),
) -> ArtifactApiRead:
    service = ArtifactService(session)
    artifact = service.update_performance(artifact_id, payload)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)
