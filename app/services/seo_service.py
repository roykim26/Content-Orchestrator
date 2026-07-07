from sqlmodel import Session, select

from app.core.ids import generate_id
from app.engines.seo_engine import SEOEngine
from app.models.seo_asset import SEOAsset, SEOAssetCreate


class SEOService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.engine = SEOEngine()

    def create_asset(self, payload: SEOAssetCreate) -> SEOAsset:
        asset = SEOAsset(
            id=generate_id("seo"),
            artifact_id=payload.artifact_id,
            topic_id=payload.topic_id,
            source_platform=payload.source_platform.lower(),
            source_url=payload.source_url,
            target_url=payload.target_url,
            anchor_text=payload.anchor_text,
            rd_domain=self.engine.extract_rd_domain(payload.source_url),
            indexed=payload.indexed,
        )
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def list_assets(self) -> list[SEOAsset]:
        statement = select(SEOAsset).order_by(SEOAsset.first_seen_at.desc())
        return list(self.session.exec(statement).all())
