from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.ids import generate_id
from app.models.automation_run import AutomationRun
from app.models.topic import Topic, TopicCreate
from app.services.feishu_topic_sync_service import FeishuTopicSyncError, FeishuTopicSyncService
from app.services.topic_inventory_alert_service import TopicInventoryAlertService
from app.services.topic_service import TopicService
from app.signals.service import TopicSignalService


@dataclass(frozen=True)
class RefillCandidateTopic:
    master_topic: str
    topic_cluster: str
    business_goal: str
    target_keyword: str
    secondary_keyword: str | None
    secondary_keywords: list[str]
    target_audience: str | None
    article_type: str | None
    content_focus: str | None
    scenes: list[str]
    target_url: str | None
    brand_name: str | None
    site: str | None
    language: str | None
    extra_rules: str | None
    priority: str
    target_platforms: list[str]
    status: str
    brief: str
    score: int
    score_breakdown: dict[str, int]


class TopicRefillService:
    AUTOMATION_TYPE = "topic_inventory_refill"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.topic_service = TopicService(session)
        self.signal_service = TopicSignalService(session)
        self.inventory_service = TopicInventoryAlertService(session)
        self.feishu_service = FeishuTopicSyncService(session)

    def run_refill(
        self,
        *,
        run_date: datetime | None = None,
        dry_run: bool = False,
        force: bool = False,
        write_to_feishu: bool = True,
    ) -> dict[str, object]:
        run_date = run_date or datetime.now(UTC)
        strategy = self._load_strategy()
        refill_config = self._refill_config(strategy)
        base_run_key = self._build_run_key(run_date)
        run_key = base_run_key
        deficits = self._calculate_deficits(refill_config)
        if dry_run:
            run_key = self._build_preview_run_key(base_run_key, run_date)

        existing_run = self._get_run_by_key(run_key)
        if existing_run and existing_run.status == "completed" and not force and not dry_run:
            if deficits:
                run_key = self._next_run_key(base_run_key)
                existing_run = self._get_run_by_key(run_key)
            else:
                return {
                    "run_id": existing_run.id,
                    "run_key": existing_run.run_key,
                    "status": existing_run.status,
                    "message": "Topic refill already completed for this run key.",
                    "summary": existing_run.summary,
                }

        if existing_run and existing_run.status == "completed" and force and not dry_run:
            run_key = self._next_run_key(base_run_key)
            existing_run = self._get_run_by_key(run_key)

        if existing_run and existing_run.status == "completed" and not force and not dry_run:
            return {
                "run_id": existing_run.id,
                "run_key": existing_run.run_key,
                "status": existing_run.status,
                "message": "Topic refill already completed for this run key.",
                "summary": existing_run.summary,
            }

        candidate_limit = min(sum(deficits.values()), int(refill_config["max_create_per_run"]))
        existing_keys = self._load_existing_keys(include_feishu=write_to_feishu)
        candidates = self._build_candidates(strategy, refill_config, deficits, existing_keys)
        selected_candidates = self._select_candidates(candidates, candidate_limit, strategy)

        run = existing_run or AutomationRun(
            id=generate_id("auto_run"),
            automation_type=self.AUTOMATION_TYPE,
            run_key=run_key,
        )
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.summary = {
            "dry_run": dry_run,
            "force": force,
            "write_to_feishu": write_to_feishu,
            "deficits": deficits,
            "candidate_count": len(candidates),
            "selected_count": len(selected_candidates),
            "created_topics": [],
        }
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        created_topics: list[dict[str, object]] = []
        feishu_warnings: list[str] = []
        if not dry_run:
            for candidate in selected_candidates:
                created_topics.append(
                    self._persist_candidate(
                        candidate,
                        run_key=run_key,
                        write_to_feishu=write_to_feishu,
                        plan_after_create=bool(refill_config["plan_after_create"]),
                        warnings=feishu_warnings,
                    )
                )

        final_summary: dict[str, object] = {
            "dry_run": dry_run,
            "force": force,
            "write_to_feishu": write_to_feishu,
            "deficits": deficits,
            "candidate_count": len(candidates),
            "selected_count": len(selected_candidates),
            "created_count": len(created_topics),
            "created_topics": created_topics,
            "preview_topics": [self._candidate_preview(item) for item in selected_candidates] if dry_run else [],
            "feishu_warnings": feishu_warnings,
            "strategy_path": str(settings.topic_strategy_path),
            "signal_sources_path": str(settings.topic_signal_sources_path),
        }
        if not dry_run and (deficits or created_topics or feishu_warnings):
            notify_payload = self._notify_refill_result(
                run_key=run_key,
                deficits=deficits,
                created_topics=created_topics,
                selected_count=len(selected_candidates),
                feishu_warnings=feishu_warnings,
                write_to_feishu=write_to_feishu,
            )
            final_summary["notify_result"] = notify_payload

        run.status = "preview" if dry_run else "completed"
        run.completed_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)
        run.summary = final_summary
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

    def _load_strategy(self) -> dict[str, Any]:
        strategy_path = Path(settings.topic_strategy_path)
        with strategy_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _refill_config(self, strategy: dict[str, Any]) -> dict[str, object]:
        raw = dict(strategy.get("auto_refill") or {})
        return {
            "enabled": bool(raw.get("enabled", True)),
            "threshold": int(raw.get("threshold", 10)),
            "target_pending": int(raw.get("target_pending", 30)),
            "max_create_per_run": int(raw.get("max_create_per_run", 50)),
            "status": str(raw.get("status", "ready") or "ready").strip().lower(),
            "plan_after_create": bool(raw.get("plan_after_create", True)),
            "feishu_only_inventory": bool(raw.get("feishu_only_inventory", False)),
            "platforms": self._configured_platforms(strategy, raw.get("platforms")),
        }

    def _configured_platforms(self, strategy: dict[str, Any], configured: Any) -> list[str]:
        if isinstance(configured, list) and configured:
            return sorted({str(item).strip().lower() for item in configured if str(item).strip()})

        platforms: set[str] = set()
        for entry in strategy.get("strategies", []):
            for platform in entry.get("target_platforms", []):
                value = str(platform).strip().lower()
                if value:
                    platforms.add(value)
        return sorted(platforms)

    def _calculate_deficits(self, refill_config: dict[str, object]) -> dict[str, int]:
        threshold = int(refill_config["threshold"])
        target_pending = int(refill_config["target_pending"])
        inventories = self.inventory_service.summarize_by_platform(
            feishu_only=bool(refill_config["feishu_only_inventory"])
        )
        pending_by_platform = {item.platform: item.pending_topic_count for item in inventories}

        deficits: dict[str, int] = {}
        for platform in refill_config["platforms"]:
            pending = pending_by_platform.get(str(platform), 0)
            if pending < threshold:
                deficits[str(platform)] = max(target_pending - pending, 0)
        return deficits

    def _load_existing_keys(self, *, include_feishu: bool) -> set[str]:
        keys: set[str] = set()
        for topic in self.session.exec(select(Topic)).all():
            self._add_existing_topic_keys(keys, topic.master_topic, topic.target_keyword)

        if include_feishu and self.feishu_service.is_configured():
            try:
                for row in self.feishu_service.fetch_topic_rows(status=None):
                    self._add_existing_topic_keys(
                        keys,
                        str(row.get("master_topic") or ""),
                        str(row.get("target_keyword") or ""),
                    )
            except FeishuTopicSyncError:
                pass
        return keys

    def _build_candidates(
        self,
        strategy: dict[str, Any],
        refill_config: dict[str, object],
        deficits: dict[str, int],
        existing_keys: set[str],
    ) -> list[RefillCandidateTopic]:
        if not bool(refill_config["enabled"]) or not deficits:
            return []

        goal_weights = dict(strategy.get("goal_weights") or {})
        priority_weights = dict(strategy.get("priority_weights") or {})
        candidates: list[RefillCandidateTopic] = []
        local_seen = set(existing_keys)

        for entry in strategy.get("strategies", []):
            base_platforms = [str(item).strip().lower() for item in entry.get("target_platforms", []) if str(item).strip()]
            matched_deficit_platforms = sorted(set(base_platforms).intersection(deficits))
            if not matched_deficit_platforms:
                continue

            cluster = str(entry["topic_cluster"]).strip()
            goal = str(entry["business_goal"]).strip()
            priority = str(entry.get("priority", "A") or "A").strip().upper()
            templates = entry.get("title_templates", [])
            strategy_keywords = self.signal_service.resolve_keywords_for_strategy(entry)

            for keyword_item in strategy_keywords:
                keyword = keyword_item.keyword.strip()
                if not keyword:
                    continue
                platforms = sorted(set(base_platforms + matched_deficit_platforms + keyword_item.target_platforms))
                secondary_keywords = self._secondary_keywords(keyword, keyword_item.source_details)
                for template in templates:
                    master_topic = str(template).format(keyword=keyword).strip()
                    if not master_topic:
                        continue
                    candidate_keys = self._topic_keys(master_topic, keyword)
                    if candidate_keys.intersection(local_seen):
                        continue
                    local_seen.update(candidate_keys)

                    platform_gap_bonus = min(sum(deficits[platform] for platform in matched_deficit_platforms), 30)
                    long_tail_bonus = 10 if len(keyword.split()) >= 3 else 4
                    signal_bonus = int(keyword_item.score)
                    goal_bonus = int(goal_weights.get(goal, 0))
                    priority_bonus = int(priority_weights.get(priority, 0))
                    target_url_bonus = 6 if entry.get("target_url") else 0
                    seo_backlink_bonus = 8 if goal == "seo_backlink" else 0
                    score_breakdown = {
                        "platform_gap_bonus": platform_gap_bonus,
                        "long_tail_bonus": long_tail_bonus,
                        "signal_bonus": signal_bonus,
                        "goal_bonus": goal_bonus,
                        "priority_bonus": priority_bonus,
                        "target_url_bonus": target_url_bonus,
                        "seo_backlink_bonus": seo_backlink_bonus,
                    }
                    brief = self._build_brief(
                        cluster=cluster,
                        keyword=keyword,
                        platforms=platforms,
                        source_names=keyword_item.source_names,
                        score_breakdown=score_breakdown,
                    )
                    candidates.append(
                        RefillCandidateTopic(
                            master_topic=master_topic,
                            topic_cluster=cluster,
                            business_goal=goal,
                            target_keyword=keyword,
                            secondary_keyword=secondary_keywords[0] if secondary_keywords else None,
                            secondary_keywords=secondary_keywords,
                            target_audience=entry.get("target_audience"),
                            article_type=entry.get("article_type"),
                            content_focus=entry.get("content_focus"),
                            scenes=[str(item).strip() for item in entry.get("scenes", []) if str(item).strip()],
                            target_url=entry.get("target_url"),
                            brand_name=entry.get("brand_name"),
                            site=entry.get("site"),
                            language=entry.get("language"),
                            extra_rules=entry.get("extra_rules"),
                            priority=priority,
                            target_platforms=platforms,
                            status=str(refill_config["status"]),
                            brief=brief,
                            score=sum(score_breakdown.values()),
                            score_breakdown=score_breakdown,
                        )
                    )

        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _persist_candidate(
        self,
        candidate: RefillCandidateTopic,
        *,
        run_key: str,
        write_to_feishu: bool,
        plan_after_create: bool,
        warnings: list[str],
    ) -> dict[str, object]:
        record_id = ""
        written_fields: list[str] = []
        if write_to_feishu:
            if self.feishu_service.is_configured():
                try:
                    feishu_result = self.feishu_service.create_topic_record(self._candidate_to_feishu_fields(candidate, run_key))
                    record_id = str(feishu_result.get("record_id") or "")
                    written_fields = list(feishu_result.get("written_fields") or [])
                except FeishuTopicSyncError as exc:
                    warnings.append(str(exc))
            else:
                warnings.append(f"Feishu config missing: {self.feishu_service.missing_config()}")

        topic = self.topic_service.create_topic(self._candidate_to_payload(candidate, record_id, run_key))
        plan_result = self.topic_service.plan_topic(topic.id) if plan_after_create else None
        return {
            "topic_id": topic.id,
            "feishu_record_id": record_id,
            "master_topic": topic.master_topic,
            "target_keyword": topic.target_keyword,
            "target_platforms": topic.target_platforms,
            "score": candidate.score,
            "score_breakdown": candidate.score_breakdown,
            "planned": bool(plan_result),
            "task_count": plan_result["task_count"] if plan_result else 0,
            "feishu_written_fields": written_fields,
        }

    def _candidate_to_payload(
        self,
        candidate: RefillCandidateTopic,
        record_id: str,
        run_key: str,
    ) -> TopicCreate:
        return TopicCreate(
            master_topic=candidate.master_topic,
            topic_cluster=candidate.topic_cluster,
            business_goal=candidate.business_goal,
            target_keyword=candidate.target_keyword,
            secondary_keyword=candidate.secondary_keyword,
            secondary_keywords=candidate.secondary_keywords,
            target_audience=candidate.target_audience,
            article_type=candidate.article_type,
            content_focus=candidate.content_focus,
            scenes=candidate.scenes,
            target_url=candidate.target_url,
            brand_name=candidate.brand_name,
            site=candidate.site,
            language=candidate.language,
            extra_rules=candidate.extra_rules,
            priority=candidate.priority,
            target_platforms=candidate.target_platforms,
            status=candidate.status,
            brief=f"{candidate.brief} Run key: {run_key}.",
            feishu_record_id=record_id or None,
            feishu_topic_id=None,
        )

    def _candidate_to_feishu_fields(self, candidate: RefillCandidateTopic, run_key: str) -> dict[str, Any]:
        fields = {
            "master_topic": candidate.master_topic,
            "topic_cluster": candidate.topic_cluster,
            "business_goal": candidate.business_goal,
            "target_keyword": candidate.target_keyword,
            "secondary_keyword": candidate.secondary_keyword or "",
            "secondary_keywords": candidate.secondary_keywords,
            "target_audience": candidate.target_audience or "",
            "article_type": candidate.article_type or "",
            "content_focus": candidate.content_focus or "",
            "scenes": candidate.scenes,
            "target_url": candidate.target_url or "",
            "brand_name": candidate.brand_name or "",
            "site": candidate.site or "",
            "language": candidate.language or "",
            "extra_rules": candidate.extra_rules or "",
            "priority": candidate.priority,
            "target_platforms": candidate.target_platforms,
            "status": candidate.status,
            "brief": f"{candidate.brief} Run key: {run_key}. SEO score: {candidate.score}.",
        }
        return {key: value for key, value in fields.items() if value not in ("", [], None)}

    @staticmethod
    def _candidate_preview(candidate: RefillCandidateTopic) -> dict[str, object]:
        return {
            "master_topic": candidate.master_topic,
            "target_keyword": candidate.target_keyword,
            "topic_cluster": candidate.topic_cluster,
            "business_goal": candidate.business_goal,
            "priority": candidate.priority,
            "target_platforms": candidate.target_platforms,
            "score": candidate.score,
            "score_breakdown": candidate.score_breakdown,
        }

    def _select_candidates(
        self,
        candidates: list[RefillCandidateTopic],
        candidate_limit: int,
        strategy: dict[str, Any],
    ) -> list[RefillCandidateTopic]:
        brand_mix = strategy.get("brand_mix")
        if not isinstance(brand_mix, dict) or candidate_limit <= 0:
            return candidates[:candidate_limit]

        takkenai_ratio = int(brand_mix.get("takkenai_subsite_ratio") or 0)
        if takkenai_ratio <= 0:
            return candidates[:candidate_limit]

        takkenai_target = round(candidate_limit * takkenai_ratio / 100)
        if takkenai_target <= 0 and candidate_limit > 0:
            takkenai_target = 1
        takkenai_target = min(takkenai_target, candidate_limit)
        ukamiru_target = candidate_limit - takkenai_target

        takkenai_candidates = [
            candidate for candidate in candidates if self._is_takkenai_candidate(candidate)
        ]
        ukamiru_candidates = [
            candidate for candidate in candidates if not self._is_takkenai_candidate(candidate)
        ]

        selected = ukamiru_candidates[:ukamiru_target] + takkenai_candidates[:takkenai_target]
        if len(selected) < candidate_limit:
            selected_ids = {id(candidate) for candidate in selected}
            selected.extend(candidate for candidate in candidates if id(candidate) not in selected_ids)

        return selected[:candidate_limit]

    @staticmethod
    def _is_takkenai_candidate(candidate: RefillCandidateTopic) -> bool:
        text = f"{candidate.topic_cluster} {candidate.master_topic} {candidate.target_keyword}".casefold()
        return "takkenai" in text or "宅建" in text

    @staticmethod
    def _build_brief(
        *,
        cluster: str,
        keyword: str,
        platforms: list[str],
        source_names: list[str],
        score_breakdown: dict[str, int],
    ) -> str:
        source_text = ", ".join(source_names) if source_names else "strategy seed"
        score_text = json.dumps(score_breakdown, ensure_ascii=False, sort_keys=True)
        return (
            f"Auto-refilled for topic inventory. Cluster: {cluster}. "
            f"SEO keyword focus: {keyword}. Platforms: {', '.join(platforms)}. "
            f"Signals: {source_text}. SEO score breakdown: {score_text}."
        )

    @staticmethod
    def _secondary_keywords(keyword: str, source_details: list[dict[str, Any]]) -> list[str]:
        candidates: list[str] = []
        for detail in source_details:
            metadata = detail.get("metadata") or {}
            for key in ("secondary_keywords", "related_keywords"):
                value = metadata.get(key)
                if isinstance(value, list):
                    candidates.extend(str(item).strip() for item in value if str(item).strip())
        if not candidates and len(keyword.split()) >= 2:
            candidates.append(keyword)
        return sorted(set(candidates))[:5]

    @classmethod
    def _add_existing_topic_keys(cls, keys: set[str], master_topic: str, target_keyword: str) -> None:
        keys.update(cls._topic_keys(master_topic, target_keyword))

    @classmethod
    def _topic_keys(cls, master_topic: str, target_keyword: str) -> set[str]:
        keys = {cls._normalize_key(master_topic), cls._normalize_key(target_keyword)}
        composite = cls._normalize_key(f"{master_topic} {target_keyword}")
        keys.add(composite)
        return {key for key in keys if key}

    @staticmethod
    def _normalize_key(value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)

    def _get_run_by_key(self, run_key: str) -> AutomationRun | None:
        statement = select(AutomationRun).where(
            AutomationRun.automation_type == self.AUTOMATION_TYPE,
            AutomationRun.run_key == run_key,
        )
        return self.session.exec(statement).first()

    def _next_run_key(self, base_run_key: str) -> str:
        for index in range(2, 100):
            candidate = f"{base_run_key}-{index:02d}"
            if not self._get_run_by_key(candidate):
                return candidate
        timestamp = datetime.now(UTC).strftime("%H%M%S")
        return f"{base_run_key}-{timestamp}"

    @staticmethod
    def _build_run_key(run_date: datetime) -> str:
        return run_date.astimezone(UTC).strftime("%Y-%m-%d")

    @staticmethod
    def _build_preview_run_key(base_run_key: str, run_date: datetime) -> str:
        return f"{base_run_key}-preview-{run_date.astimezone(UTC).strftime('%H%M%S')}"

    def _notify_refill_result(
        self,
        *,
        run_key: str,
        deficits: dict[str, int],
        created_topics: list[dict[str, object]],
        selected_count: int,
        feishu_warnings: list[str],
        write_to_feishu: bool,
    ) -> dict[str, object]:
        text = self._build_refill_notification_text(
            run_key=run_key,
            deficits=deficits,
            created_topics=created_topics,
            selected_count=selected_count,
            feishu_warnings=feishu_warnings,
            write_to_feishu=write_to_feishu,
        )
        try:
            notify_result = self.feishu_service.notify_text(text)
            return {"notified": True, "message": text, "notify_result": notify_result}
        except FeishuTopicSyncError as exc:
            return {"notified": False, "message": text, "notify_error": str(exc)}

    @staticmethod
    def _build_refill_notification_text(
        *,
        run_key: str,
        deficits: dict[str, int],
        created_topics: list[dict[str, object]],
        selected_count: int,
        feishu_warnings: list[str],
        write_to_feishu: bool,
    ) -> str:
        created_count = len(created_topics)
        planned_count = sum(1 for item in created_topics if item.get("planned"))
        task_count = sum(int(item.get("task_count") or 0) for item in created_topics)
        lines = [
            "Content Orchestrator 自动补主题完成",
            f"运行批次：{run_key}",
            f"触发缺口：{json.dumps(deficits, ensure_ascii=False, sort_keys=True)}",
            f"候选入选：{selected_count}",
            f"已创建主题：{created_count}",
            f"已生成发布任务的主题：{planned_count}",
            f"发布任务数量：{task_count}",
            f"写入飞书主题表：{'是' if write_to_feishu else '否'}",
        ]
        if created_topics:
            lines.append("新主题预览：")
            for index, item in enumerate(created_topics[:5], start=1):
                platforms = ", ".join(str(platform) for platform in item.get("target_platforms", []))
                lines.append(
                    f"{index}. {item.get('master_topic')} | 关键词：{item.get('target_keyword')} "
                    f"| 平台：{platforms or '-'} | 分数：{item.get('score')}"
                )
            if len(created_topics) > 5:
                lines.append(f"还有 {len(created_topics) - 5} 个主题未展示。")
        if feishu_warnings:
            lines.append("飞书写入警告：")
            lines.extend(f"- {warning}" for warning in feishu_warnings[:5])
        return "\n".join(lines)
