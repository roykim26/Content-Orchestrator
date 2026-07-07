from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.core.ids import generate_id
from app.models.automation_run import AutomationRun
from app.models.topic import Topic, TopicCreate
from app.signals.service import TopicSignalService
from app.services.topic_service import TopicService


@dataclass
class CandidateTopic:
    master_topic: str
    topic_cluster: str
    business_goal: str
    target_keyword: str
    priority: str
    target_platforms: list[str]
    brief: str
    score: int
    score_breakdown: dict[str, int]


class AutomatedTopicService:
    AUTOMATION_TYPE = "weekly_topic_selection"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.topic_service = TopicService(session)
        self.signal_service = TopicSignalService(session)

    def run_weekly_selection(
        self,
        run_date: datetime | None = None,
        force: bool = False,
    ) -> dict[str, object]:
        run_date = run_date or datetime.now(UTC)
        run_key = self._build_run_key(run_date)
        existing_run = self._get_run_by_key(run_key)
        if existing_run and existing_run.status == "completed" and not force:
            return {
                "run_id": existing_run.id,
                "run_key": existing_run.run_key,
                "status": existing_run.status,
                "message": "Weekly topic selection already completed for this run key.",
                "summary": existing_run.summary,
            }

        strategy = self._load_strategy()
        selected_count = int(strategy.get("weekly_topic_limit", 3))
        lookback_days = int(strategy.get("duplicate_lookback_days", 42))
        recent_topics = self._load_recent_topics(run_date, lookback_days)
        candidates = self._build_candidates(strategy, recent_topics)
        selected_candidates = self._select_candidates(candidates, selected_count, strategy)

        run = existing_run or AutomationRun(
            id=generate_id("auto_run"),
            automation_type=self.AUTOMATION_TYPE,
            run_key=run_key,
        )
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.summary = {
            "candidate_count": len(candidates),
            "selected_count": len(selected_candidates),
            "selected_topics": [],
            "force": force,
            "signal_preview": self.signal_service.preview_strategy_keywords(),
        }
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        created_topics: list[dict[str, object]] = []
        for candidate in selected_candidates:
            topic = self._create_topic_from_candidate(candidate, run_key)
            plan_result = self.topic_service.plan_topic(topic.id)
            created_topics.append(
                {
                    "topic_id": topic.id,
                    "master_topic": topic.master_topic,
                    "target_keyword": topic.target_keyword,
                    "priority": topic.priority,
                    "score": candidate.score,
                    "score_breakdown": candidate.score_breakdown,
                    "task_count": plan_result["task_count"] if plan_result else 0,
                }
            )

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.summary = {
            "candidate_count": len(candidates),
            "selected_count": len(selected_candidates),
            "selected_topics": created_topics,
            "force": force,
            "strategy_path": str(settings.topic_strategy_path),
            "signal_sources_path": str(settings.topic_signal_sources_path),
            "signal_preview": self.signal_service.preview_strategy_keywords(),
        }
        run.updated_at = datetime.now(UTC)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        return {
            "run_id": run.id,
            "run_key": run.run_key,
            "status": run.status,
            "summary": run.summary,
        }

    def list_runs(self, limit: int = 10) -> list[AutomationRun]:
        statement = (
            select(AutomationRun)
            .where(AutomationRun.automation_type == self.AUTOMATION_TYPE)
            .order_by(AutomationRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement).all())

    def _load_strategy(self) -> dict[str, object]:
        strategy_path = Path(settings.topic_strategy_path)
        with strategy_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _load_recent_topics(self, run_date: datetime, lookback_days: int) -> list[Topic]:
        since = run_date - timedelta(days=lookback_days)
        statement = select(Topic).where(Topic.created_at >= since)
        return list(self.session.exec(statement).all())

    def _build_candidates(
        self,
        strategy: dict[str, object],
        recent_topics: list[Topic],
    ) -> list[CandidateTopic]:
        candidates: list[CandidateTopic] = []
        goal_weights = strategy.get("goal_weights", {})
        priority_weights = strategy.get("priority_weights", {})
        cluster_penalty = int(strategy.get("cluster_repeat_penalty", 15))
        strategies = strategy.get("strategies", [])

        for entry in strategies:
            cluster = entry["topic_cluster"].strip()
            goal = entry["business_goal"].strip()
            priority = entry.get("priority", "A").strip().upper()
            base_platforms = [platform.strip().lower() for platform in entry.get("target_platforms", [])]
            strategy_keywords = self.signal_service.resolve_keywords_for_strategy(entry)
            templates = entry.get("title_templates", [])

            cluster_repeats = sum(1 for topic in recent_topics if topic.topic_cluster == cluster)
            for keyword_item in strategy_keywords:
                normalized_keyword = keyword_item.keyword.strip()
                platforms = sorted(set(base_platforms + [platform.lower() for platform in keyword_item.target_platforms]))
                duplicate_hits = self._count_duplicate_hits(normalized_keyword, recent_topics)
                freshness_bonus = max(0, 30 - duplicate_hits * 10)
                platform_bonus = min(len(platforms) * 2, 12)
                goal_bonus = int(goal_weights.get(goal, 0))
                priority_bonus = int(priority_weights.get(priority, 0))
                saturation_penalty = cluster_repeats * cluster_penalty
                signal_bonus = keyword_item.score

                for template in templates:
                    master_topic = template.format(keyword=normalized_keyword).strip()
                    brief = (
                        f"Auto-selected for {cluster}. "
                        f"Keyword focus: {normalized_keyword}. "
                        f"Generated by weekly topic automation."
                    )
                    if keyword_item.source_names:
                        brief += f" Signals: {', '.join(keyword_item.source_names)}."
                    score_breakdown = {
                        "freshness_bonus": freshness_bonus,
                        "platform_bonus": platform_bonus,
                        "goal_bonus": goal_bonus,
                        "priority_bonus": priority_bonus,
                        "signal_bonus": signal_bonus,
                        "saturation_penalty": -saturation_penalty,
                    }
                    score = sum(score_breakdown.values())
                    candidates.append(
                        CandidateTopic(
                            master_topic=master_topic,
                            topic_cluster=cluster,
                            business_goal=goal,
                            target_keyword=normalized_keyword,
                            priority=priority,
                            target_platforms=platforms,
                            brief=brief,
                            score=score,
                            score_breakdown=score_breakdown,
                        )
                    )

        deduplicated = self._deduplicate_candidates(candidates, recent_topics)
        return sorted(deduplicated, key=lambda item: item.score, reverse=True)

    def _deduplicate_candidates(
        self,
        candidates: list[CandidateTopic],
        recent_topics: list[Topic],
    ) -> list[CandidateTopic]:
        seen_master_topics = {topic.master_topic.casefold() for topic in recent_topics}
        seen_keywords = {topic.target_keyword.casefold() for topic in recent_topics}
        unique_candidates: list[CandidateTopic] = []
        local_seen: set[str] = set()

        for candidate in candidates:
            topic_key = candidate.master_topic.casefold()
            keyword_key = candidate.target_keyword.casefold()
            if topic_key in seen_master_topics or keyword_key in seen_keywords:
                continue
            if topic_key in local_seen or keyword_key in local_seen:
                continue
            unique_candidates.append(candidate)
            local_seen.add(topic_key)
            local_seen.add(keyword_key)

        return unique_candidates

    def _select_candidates(
        self,
        candidates: list[CandidateTopic],
        selected_count: int,
        strategy: dict[str, object],
    ) -> list[CandidateTopic]:
        brand_mix = strategy.get("brand_mix")
        if not isinstance(brand_mix, dict) or selected_count <= 0:
            return candidates[:selected_count]

        takkenai_ratio = int(brand_mix.get("takkenai_subsite_ratio") or 0)
        if takkenai_ratio <= 0:
            return candidates[:selected_count]

        takkenai_target = round(selected_count * takkenai_ratio / 100)
        if takkenai_target <= 0 and selected_count > 0:
            takkenai_target = 1
        takkenai_target = min(takkenai_target, selected_count)
        ukamiru_target = selected_count - takkenai_target

        takkenai_candidates = [
            candidate for candidate in candidates if self._is_takkenai_candidate(candidate)
        ]
        ukamiru_candidates = [
            candidate for candidate in candidates if not self._is_takkenai_candidate(candidate)
        ]

        selected = ukamiru_candidates[:ukamiru_target] + takkenai_candidates[:takkenai_target]
        if len(selected) < selected_count:
            selected_ids = {id(candidate) for candidate in selected}
            selected.extend(candidate for candidate in candidates if id(candidate) not in selected_ids)

        return selected[:selected_count]

    @staticmethod
    def _is_takkenai_candidate(candidate: CandidateTopic) -> bool:
        text = f"{candidate.topic_cluster} {candidate.master_topic} {candidate.target_keyword}".casefold()
        return "takkenai" in text or "宅建" in text

    def _count_duplicate_hits(self, keyword: str, recent_topics: list[Topic]) -> int:
        keyword_key = keyword.casefold()
        return sum(1 for topic in recent_topics if topic.target_keyword.casefold() == keyword_key)

    def _create_topic_from_candidate(self, candidate: CandidateTopic, run_key: str) -> Topic:
        payload = TopicCreate(
            master_topic=candidate.master_topic,
            topic_cluster=candidate.topic_cluster,
            business_goal=candidate.business_goal,
            target_keyword=candidate.target_keyword,
            priority=candidate.priority,
            target_platforms=candidate.target_platforms,
            status="ready",
            brief=f"{candidate.brief} Run key: {run_key}.",
        )
        return self.topic_service.create_topic(payload)

    def _get_run_by_key(self, run_key: str) -> AutomationRun | None:
        statement = select(AutomationRun).where(
            AutomationRun.automation_type == self.AUTOMATION_TYPE,
            AutomationRun.run_key == run_key,
        )
        return self.session.exec(statement).first()

    def _build_run_key(self, run_date: datetime) -> str:
        iso_year, iso_week, _ = run_date.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
