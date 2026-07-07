from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.models.seo_asset import SEOAsset, SEOAssetCreate, SEOAssetRead
from app.services.seo_service import SEOService

router = APIRouter()


@router.post("", response_model=SEOAssetRead)
def create_seo_asset(payload: SEOAssetCreate, session: Session = Depends(get_session)) -> SEOAsset:
    service = SEOService(session)
    return service.create_asset(payload)


@router.get("", response_model=list[SEOAssetRead])
def list_seo_assets(session: Session = Depends(get_session)) -> list[SEOAsset]:
    service = SEOService(session)
    return service.list_assets()
