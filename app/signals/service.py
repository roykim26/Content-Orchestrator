from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.core.config import settings
from app.feedback.service import TopicFeedbackService
from app.models.artifact import ContentArtifact
from app.models.seo_asset import SEOAsset
from app.signals.models import StrategyKeyword, TopicSignal


class TopicSignalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.feedback_service = TopicFeedbackService(session)

    def list_signals(self) -> list[TopicSignal]:
        config = self._load_config()
        signals: list[TopicSignal] = []
        for source in config.get("sources", []):
            source_type = source.get("type")
            if source_type == "static_keywords":
                signals.extend(self._collect_static_keywords(source))
            elif source_type == "json_file":
                signals.extend(self._collect_json_file(source))
            elif source_type == "artifact_metadata":
                signals.extend(self._collect_artifact_metadata(source))
            elif source_type == "seo_asset_anchors":
                signals.extend(self._collect_seo_asset_anchors(source))
            elif source_type == "published_topic_winners":
                signals.extend(self._collect_published_topic_winners(source))
            elif source_type == "platform_gap_feedback":
                signals.extend(self._collect_platform_gap_feedback(source))
        return signals

    def resolve_keywords_for_strategy(self, strategy_entry: dict[str, Any]) -> list[StrategyKeyword]:
        configured_keywords = [
            StrategyKeyword(keyword=keyword.strip(), score=0)
            for keyword in strategy_entry.get("keywords", [])
            if keyword.strip()
        ]
        source_names = {name.strip() for name in strategy_entry.get("signal_source_names", []) if name.strip()}
        if not source_names:
            return configured_keywords

        matched_signals = self._match_signals(strategy_entry, source_names)
        signal_keywords = self._merge_signal_keywords(matched_signals)

        merged: dict[str, StrategyKeyword] = {item.keyword.casefold(): item for item in configured_keywords}
        for item in signal_keywords:
            key = item.keyword.casefold()
            if key in merged:
                merged[key].score = max(merged[key].score, item.score)
                merged[key].target_platforms = sorted(
                    set(merged[key].target_platforms + item.target_platforms)
                )
                merged[key].source_names = sorted(set(merged[key].source_names + item.source_names))
                merged[key].source_details.extend(item.source_details)
            else:
                merged[key] = item

        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def preview_strategy_keywords(self) -> list[dict[str, object]]:
        config = self._load_config()
        signals = self.list_signals()
        previews: list[dict[str, object]] = []
        for source in config.get("sources", []):
            previews.append(
                {
                    "source_name": source.get("name"),
                    "source_type": source.get("type"),
                    "signal_count": len(
                        [signal for signal in signals if signal.source_name == source.get("name")]
                    ),
                }
            )
        return previews

    def _match_signals(
        self,
        strategy_entry: dict[str, Any],
        source_names: set[str],
    ) -> list[TopicSignal]:
        cluster = strategy_entry.get("topic_cluster")
        goal = strategy_entry.get("business_goal")
        signals: list[TopicSignal] = []
        for signal in self.list_signals():
            if signal.source_name not in source_names:
                continue
            if signal.topic_cluster and signal.topic_cluster != cluster:
                continue
            if signal.business_goal and signal.business_goal != goal:
                continue
            signals.append(signal)
        return signals

    def _merge_signal_keywords(self, signals: list[TopicSignal]) -> list[StrategyKeyword]:
        merged: dict[str, StrategyKeyword] = {}
        for signal in signals:
            key = signal.keyword.casefold()
            detail = {
                "source_name": signal.source_name,
                "source_type": signal.source_type,
                "score": signal.score,
                "metadata": signal.metadata,
            }
            if key not in merged:
                merged[key] = StrategyKeyword(
                    keyword=signal.keyword,
                    score=signal.score,
                    target_platforms=sorted({platform.lower() for platform in signal.target_platforms}),
                    source_names=[signal.source_name],
                    source_details=[detail],
                )
                continue
            merged_item = merged[key]
            merged_item.score += signal.score
            merged_item.target_platforms = sorted(
                set(merged_item.target_platforms + [platform.lower() for platform in signal.target_platforms])
            )
            merged_item.source_names = sorted(set(merged_item.source_names + [signal.source_name]))
            merged_item.source_details.append(detail)
        return list(merged.values())

    def _collect_static_keywords(self, source: dict[str, Any]) -> list[TopicSignal]:
        signals: list[TopicSignal] = []
        for keyword in source.get("keywords", []):
            value = keyword.get("keyword", "").strip()
            if not value:
                continue
            signals.append(
                TopicSignal(
                    keyword=value,
                    source_name=source["name"],
                    source_type="static_keywords",
                    score=int(keyword.get("score", source.get("default_score", 10))),
                    topic_cluster=keyword.get("topic_cluster") or source.get("topic_cluster"),
                    business_goal=keyword.get("business_goal") or source.get("business_goal"),
                    priority=keyword.get("priority") or source.get("priority"),
                    target_platforms=keyword.get("target_platforms", source.get("target_platforms", [])),
                    metadata={"label": keyword.get("label")},
                )
            )
        return signals

    def _collect_json_file(self, source: dict[str, Any]) -> list[TopicSignal]:
        file_path = Path(source.get("path", ""))
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.exists():
            return []

        with file_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        signals: list[TopicSignal] = []
        for item in payload:
            keyword = str(item.get("keyword", "")).strip()
            if not keyword:
                continue
            signals.append(
                TopicSignal(
                    keyword=keyword,
                    source_name=source["name"],
                    source_type="json_file",
                    score=int(item.get("score", source.get("default_score", 8))),
                    topic_cluster=item.get("topic_cluster") or source.get("topic_cluster"),
                    business_goal=item.get("business_goal") or source.get("business_goal"),
                    priority=item.get("priority") or source.get("priority"),
                    target_platforms=item.get("target_platforms", source.get("target_platforms", [])),
                    metadata={
                        "origin": item.get("origin"),
                        "captured_at": item.get("captured_at"),
                    },
                )
            )
        return signals

    def _collect_artifact_metadata(self, source: dict[str, Any]) -> list[TopicSignal]:
        min_count = int(source.get("min_count", 1))
        limit = int(source.get("limit", 20))
        score = int(source.get("default_score", 6))
        statement = select(ContentArtifact).where(ContentArtifact.published == True)  # noqa: E712
        try:
            artifacts = list(self.session.exec(statement).all())
        except SQLAlchemyError:
            return []

        counts: dict[tuple[str, str | None, str | None], int] = defaultdict(int)
        for artifact in artifacts:
            keyword = str(artifact.extra_metadata.get("target_keyword", "")).strip()
            if not keyword:
                continue
            counts[(keyword, artifact.extra_metadata.get("topic_cluster"), artifact.extra_metadata.get("business_goal"))] += 1

        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
        signals: list[TopicSignal] = []
        for (keyword, cluster, goal), count in ranked:
            if count < min_count:
                continue
            signals.append(
                TopicSignal(
                    keyword=keyword,
                    source_name=source["name"],
                    source_type="artifact_metadata",
                    score=score + count,
                    topic_cluster=cluster or source.get("topic_cluster"),
                    business_goal=goal or source.get("business_goal"),
                    metadata={"published_artifact_count": count},
                )
            )
        return signals

    def _collect_seo_asset_anchors(self, source: dict[str, Any]) -> list[TopicSignal]:
        min_count = int(source.get("min_count", 1))
        limit = int(source.get("limit", 20))
        score = int(source.get("default_score", 5))
        try:
            assets = list(self.session.exec(select(SEOAsset)).all())
        except SQLAlchemyError:
            return []

        counts: dict[str, int] = defaultdict(int)
        for asset in assets:
            keyword = asset.anchor_text.strip()
            if not keyword:
                continue
            counts[keyword] += 1

        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
        signals: list[TopicSignal] = []
        for keyword, count in ranked:
            if count < min_count:
                continue
            signals.append(
                TopicSignal(
                    keyword=keyword,
                    source_name=source["name"],
                    source_type="seo_asset_anchors",
                    score=score + count,
                    topic_cluster=source.get("topic_cluster"),
                    business_goal=source.get("business_goal"),
                    metadata={"anchor_occurrences": count},
                )
            )
        return signals

    def _collect_published_topic_winners(self, source: dict[str, Any]) -> list[TopicSignal]:
        default_score = int(source.get("default_score", 10))
        limit = int(source.get("limit", 20))
        try:
            return self.feedback_service.build_winner_signals(default_score=default_score, limit=limit)
        except SQLAlchemyError:
            return []

    def _collect_platform_gap_feedback(self, source: dict[str, Any]) -> list[TopicSignal]:
        default_score = int(source.get("default_score", 8))
        limit = int(source.get("limit", 20))
        try:
            return self.feedback_service.build_gap_signals(default_score=default_score, limit=limit)
        except SQLAlchemyError:
            return []

    def _load_config(self) -> dict[str, Any]:
        path = Path(settings.topic_signal_sources_path)
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
