from __future__ import annotations

from collections import defaultdict

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.models.artifact import ContentArtifact
from app.models.seo_asset import SEOAsset
from app.models.topic import Topic
from app.signals.models import TopicSignal


class TopicFeedbackService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build_winner_signals(self, default_score: int = 10, limit: int = 20) -> list[TopicSignal]:
        topics = self._load_topics()
        published_artifacts = self._load_published_artifacts()
        seo_assets = self._load_seo_assets()

        seo_by_topic: dict[str, int] = defaultdict(int)
        for asset in seo_assets:
            seo_by_topic[asset.topic_id] += 1

        artifacts_by_topic: dict[str, list[ContentArtifact]] = defaultdict(list)
        for artifact in published_artifacts:
            artifacts_by_topic[artifact.topic_id].append(artifact)

        ranked: list[tuple[int, Topic, list[ContentArtifact], int, dict[str, int]]] = []
        for topic_id, artifacts in artifacts_by_topic.items():
            topic = topics.get(topic_id)
            if not topic:
                continue
            distinct_platforms = len({artifact.platform for artifact in artifacts})
            seo_count = seo_by_topic.get(topic_id, 0)
            performance = self._aggregate_performance(artifacts)
            performance_score = self._calculate_performance_score(performance)
            score = default_score + len(artifacts) * 3 + distinct_platforms * 2 + seo_count * 2 + performance_score
            ranked.append((score, topic, artifacts, seo_count, performance))

        ranked.sort(key=lambda item: item[0], reverse=True)
        signals: list[TopicSignal] = []
        for score, topic, artifacts, seo_count, performance in ranked[:limit]:
            winning_platforms = sorted({artifact.platform for artifact in artifacts})
            signals.append(
                TopicSignal(
                    keyword=topic.target_keyword,
                    source_name="published_topic_winners",
                    source_type="published_topic_winners",
                    score=score,
                    topic_cluster=topic.topic_cluster,
                    business_goal=topic.business_goal,
                    priority=topic.priority,
                    target_platforms=winning_platforms,
                    metadata={
                        "published_artifact_count": len(artifacts),
                        "winning_platforms": winning_platforms,
                        "seo_asset_count": seo_count,
                        "performance": performance,
                        "topic_id": topic.id,
                    },
                )
            )
        return signals

    def build_gap_signals(self, default_score: int = 8, limit: int = 20) -> list[TopicSignal]:
        topics = self._load_topics()
        published_artifacts = self._load_published_artifacts()

        published_platforms_by_topic: dict[str, set[str]] = defaultdict(set)
        for artifact in published_artifacts:
            published_platforms_by_topic[artifact.topic_id].add(artifact.platform)

        ranked: list[tuple[int, Topic, list[str], list[str]]] = []
        for topic in topics.values():
            target_platforms = {platform.lower() for platform in topic.target_platforms}
            if not target_platforms:
                continue
            published_platforms = published_platforms_by_topic.get(topic.id, set())
            if not published_platforms:
                continue
            missing_platforms = sorted(target_platforms - published_platforms)
            if not missing_platforms:
                continue
            score = default_score + len(missing_platforms) * 4 + len(published_platforms) * 2
            ranked.append((score, topic, sorted(published_platforms), missing_platforms))

        ranked.sort(key=lambda item: item[0], reverse=True)
        signals: list[TopicSignal] = []
        for score, topic, published_platforms, missing_platforms in ranked[:limit]:
            signals.append(
                TopicSignal(
                    keyword=topic.target_keyword,
                    source_name="platform_gap_feedback",
                    source_type="platform_gap_feedback",
                    score=score,
                    topic_cluster=topic.topic_cluster,
                    business_goal=topic.business_goal,
                    priority=topic.priority,
                    target_platforms=missing_platforms,
                    metadata={
                        "topic_id": topic.id,
                        "published_platforms": published_platforms,
                        "missing_platforms": missing_platforms,
                    },
                )
            )
        return signals

    def summarize(self) -> dict[str, object]:
        try:
            winner_signals = self.build_winner_signals()
            gap_signals = self.build_gap_signals()
        except SQLAlchemyError:
            winner_signals = []
            gap_signals = []
        return {
            "winner_signal_count": len(winner_signals),
            "gap_signal_count": len(gap_signals),
            "winner_examples": [
                {
                    "keyword": signal.keyword,
                    "score": signal.score,
                    "metadata": signal.metadata,
                }
                for signal in winner_signals[:5]
            ],
            "gap_examples": [
                {
                    "keyword": signal.keyword,
                    "score": signal.score,
                    "metadata": signal.metadata,
                }
                for signal in gap_signals[:5]
            ],
        }

    def _load_topics(self) -> dict[str, Topic]:
        return {topic.id: topic for topic in self.session.exec(select(Topic)).all()}

    def _load_published_artifacts(self) -> list[ContentArtifact]:
        statement = select(ContentArtifact).where(ContentArtifact.published == True)  # noqa: E712
        try:
            return list(self.session.exec(statement).all())
        except SQLAlchemyError:
            return []

    def _load_seo_assets(self) -> list[SEOAsset]:
        try:
            return list(self.session.exec(select(SEOAsset)).all())
        except SQLAlchemyError:
            return []

    def _aggregate_performance(self, artifacts: list[ContentArtifact]) -> dict[str, int]:
        totals = {
            "views": 0,
            "clicks": 0,
            "conversions": 0,
            "likes": 0,
            "shares": 0,
            "comments": 0,
        }
        for artifact in artifacts:
            performance = artifact.extra_metadata.get("performance", {})
            for key in totals:
                value = performance.get(key, 0)
                if isinstance(value, int):
                    totals[key] += value
        return totals

    def _calculate_performance_score(self, performance: dict[str, int]) -> int:
        views_score = min(performance["views"] // 100, 10)
        clicks_score = min(performance["clicks"] * 2, 20)
        conversions_score = min(performance["conversions"] * 5, 25)
        engagement_score = min(
            performance["likes"] + performance["shares"] * 2 + performance["comments"] * 2,
            20,
        )
        return views_score + clicks_score + conversions_score + engagement_score
