from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TopicSignal:
    keyword: str
    source_name: str
    source_type: str
    score: int
    topic_cluster: str | None = None
    business_goal: str | None = None
    priority: str | None = None
    target_platforms: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class StrategyKeyword:
    keyword: str
    score: int
    target_platforms: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)
    source_details: list[dict[str, object]] = field(default_factory=list)
