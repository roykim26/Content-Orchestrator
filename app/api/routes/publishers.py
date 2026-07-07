from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.deps import require_publisher_auth
from app.db import get_session
from app.models.artifact import (
    ArtifactClaimRequest,
    ArtifactClaimResponse,
    ArtifactPublishEnvelope,
    ArtifactPublishResult,
    ArtifactApiRead,
)
from app.services.publisher_service import PublisherService

router = APIRouter()


@router.get("/artifacts", response_model=list[ArtifactPublishEnvelope])
def get_publishable_artifacts(
    platform: str = Query(...),
    status: str = Query(default="publish_pending"),
    account: str | None = Query(default=None),
    note_account: str | None = Query(default=None),
    _: None = Depends(require_publisher_auth),
    session: Session = Depends(get_session),
) -> list[ArtifactPublishEnvelope]:
    service = PublisherService(session)
    artifacts = service.list_publishable_artifacts(
        platform=platform,
        status=status,
        account=account,
        note_account=note_account,
    )
    return [ArtifactPublishEnvelope.from_model(artifact) for artifact in artifacts]


@router.post("/claims", response_model=ArtifactClaimResponse)
def claim_publishable_artifacts(
    payload: ArtifactClaimRequest,
    _: None = Depends(require_publisher_auth),
    session: Session = Depends(get_session),
) -> ArtifactClaimResponse:
    service = PublisherService(session)
    artifacts = service.claim_artifacts(payload)
    return ArtifactClaimResponse(
        consumer_name=payload.consumer_name,
        claimed_count=len(artifacts),
        artifacts=[ArtifactPublishEnvelope.from_model(artifact) for artifact in artifacts],
    )


@router.post("/artifacts/{artifact_id}/publish-result", response_model=ArtifactApiRead)
def write_publish_result(
    artifact_id: str,
    payload: ArtifactPublishResult,
    _: None = Depends(require_publisher_auth),
    session: Session = Depends(get_session),
) -> ArtifactApiRead:
    service = PublisherService(session)
    artifact = service.write_publish_result(artifact_id, payload)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApiRead.from_model(artifact)


@router.post("/recover-stale-publishing")
def recover_stale_publishing(
    timeout_minutes: int = Query(default=30, ge=1),
    artifact_id: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    dry_run: bool = Query(default=False),
    _: None = Depends(require_publisher_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    service = PublisherService(session)
    artifacts = service.recover_stale_publishing(
        timeout_minutes=timeout_minutes,
        requested_by=requested_by,
        artifact_id=artifact_id,
        dry_run=dry_run,
    )
    return {
        "recovered_count": len(artifacts),
        "dry_run": dry_run,
        "artifacts": [ArtifactApiRead.from_model(artifact) for artifact in artifacts],
    }
