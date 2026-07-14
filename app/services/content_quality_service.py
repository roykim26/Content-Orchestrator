from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from app.models.topic import Topic


FACTS_PATH = Path(__file__).resolve().parents[1] / "content_facts" / "ukamiru_product_facts.json"
LONG_FORM_PLATFORMS = {"ameba", "hatena", "livedoor", "note", "zenn"}


@dataclass
class ContentQualityReport:
    score: int = 100
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def publish_blocked(self) -> bool:
        return bool(self.errors) or self.score < 75

    def add_error(self, message: str, penalty: int) -> None:
        if message not in self.errors:
            self.errors.append(message)
            self.score = max(self.score - penalty, 0)

    def add_warning(self, message: str, penalty: int) -> None:
        if message not in self.warnings:
            self.warnings.append(message)
            self.score = max(self.score - penalty, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "publish_blocked": self.publish_blocked,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


class UkamiruProductFacts:
    def __init__(self, path: Path = FACTS_PATH) -> None:
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8"))

    @property
    def version(self) -> str:
        return str(self.data.get("version") or "unknown")

    @property
    def canonical_home(self) -> str:
        return str(self.data.get("canonical_home") or "https://www.ukamiru.jp/")

    def platform_role(self, platform: str) -> str:
        return str((self.data.get("platform_roles") or {}).get(platform.lower()) or "")

    def verified_capabilities(self) -> list[str]:
        return [str(item) for item in self.data.get("verified_capabilities", [])]

    def forbidden_claim_patterns(self) -> list[str]:
        return [str(item) for item in self.data.get("forbidden_claim_patterns", [])]

    def resolve_target_url(self, topic: Topic) -> str:
        topic_text = " ".join(
            filter(
                None,
                [
                    topic.master_topic,
                    topic.target_keyword,
                    topic.secondary_keyword or "",
                    topic.content_focus or "",
                    topic.article_type or "",
                ],
            )
        )
        routes = self.data.get("exam_routes") or {}
        for exam_name in sorted(routes, key=len, reverse=True):
            if exam_name in topic_text:
                return str(routes[exam_name])

        configured = str(topic.target_url or "").strip()
        if configured and not self._is_ukamiru_home(configured):
            return configured
        return self.canonical_home

    def requires_manual_review(self, topic: Topic, title: str = "", content: str = "") -> bool:
        clusters = {str(item) for item in self.data.get("manual_review_topic_clusters", [])}
        if topic.topic_cluster in clusters:
            return True
        text = " ".join(
            [
                topic.master_topic,
                topic.article_type or "",
                topic.content_focus or "",
                title,
                content,
            ]
        )
        return any(str(term) in text for term in self.data.get("manual_review_terms", []))

    def prompt_context(self, platform: str) -> str:
        capabilities = "\n".join(f"- {item}" for item in self.verified_capabilities())
        forbidden = "\n".join(f"- {item}" for item in self.forbidden_claim_patterns())
        return (
            f"Product facts version: {self.version}\n"
            f"Platform role: {self.platform_role(platform)}\n"
            "Only the following Ukamiru capability claims are verified:\n"
            f"{capabilities}\n"
            "Never state or imply these unverified/forbidden claims:\n"
            f"{forbidden}"
        )

    @staticmethod
    def _is_ukamiru_home(url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.netloc.lower() in {"ukamiru.jp", "www.ukamiru.jp"} and parsed.path in {"", "/"}


class ContentQualityService:
    def __init__(self, facts: UkamiruProductFacts | None = None) -> None:
        self.facts = facts or UkamiruProductFacts()

    def evaluate(
        self,
        *,
        title: str,
        content: str,
        topic: Topic,
        platform: str,
        target_url: str = "",
        comparison_contents: Iterable[str] = (),
    ) -> ContentQualityReport:
        report = ContentQualityReport()
        platform_key = platform.lower()
        report.checks["facts_version"] = self.facts.version
        report.checks["platform_role"] = self.facts.platform_role(platform_key)
        report.checks["resolved_target_url"] = target_url or self.facts.resolve_target_url(topic)

        self._check_keyword_naturalness(report, title, content, topic)
        self._check_title_promise(report, title, content)
        self._check_forbidden_claims(report, title, content)
        self._check_links(report, content, platform_key, report.checks["resolved_target_url"])
        self._check_information_gain(report, content, platform_key)
        self._check_cross_platform_similarity(report, content, comparison_contents)
        return report

    def _check_keyword_naturalness(
        self,
        report: ContentQualityReport,
        title: str,
        content: str,
        topic: Topic,
    ) -> None:
        keyword = str(topic.target_keyword or "").strip()
        if " " not in keyword:
            return
        exact_count = f"{title}\n{content}".count(keyword)
        report.checks["exact_spaced_keyword_count"] = exact_count
        if exact_count:
            report.add_error(
                "带空格的日语搜索查询被原样写入标题或正文；必须改写为自然日语。",
                25,
            )

    @staticmethod
    def _check_title_promise(report: ContentQualityReport, title: str, content: str) -> None:
        if not any(term in title for term in ("手順", "始め方", "使い方")):
            return
        step_headings = len(re.findall(r"(?m)^##\s*(?:ステップ|Step|STEP|手順|\d+[.．、:：])", content))
        numbered_items = len(re.findall(r"(?m)^\s*(?:\d+[.．、)]|[①-⑩])\s*", content))
        total_steps = max(step_headings, numbered_items)
        report.checks["promised_step_count"] = total_steps
        if total_steps < 3:
            report.add_error(
                "标题承诺了步骤或使用方法，但正文没有至少3个可执行步骤。",
                25,
            )

    def _check_forbidden_claims(self, report: ContentQualityReport, title: str, content: str) -> None:
        text = f"{title}\n{content}"
        matches = [pattern for pattern in self.facts.forbidden_claim_patterns() if pattern in text]
        report.checks["forbidden_claim_matches"] = matches
        if matches:
            report.add_error(
                f"出现未经产品事实库确认的功能或承诺：{' / '.join(matches)}",
                40,
            )

    @staticmethod
    def _check_links(
        report: ContentQualityReport,
        content: str,
        platform: str,
        resolved_target_url: str,
    ) -> None:
        if platform not in LONG_FORM_PLATFORMS:
            return
        urls = re.findall(r"https?://[^\s)]+", content)
        report.checks["link_count"] = len(urls)
        if not urls:
            report.add_warning("长文没有可访问的目标链接。", 10)
        elif len(urls) > 3:
            report.add_warning("长文链接超过3个，需确认每个链接都服务于读者路径。", 5)
        if resolved_target_url and urls:
            expected_host = urlsplit(resolved_target_url).netloc.lower().removeprefix("www.")
            if not any(
                urlsplit(url).netloc.lower().removeprefix("www.") == expected_host
                for url in urls
            ):
                report.add_warning("正文链接没有指向系统为该考试或意图解析出的目标页。", 10)

    @staticmethod
    def _check_information_gain(report: ContentQualityReport, content: str, platform: str) -> None:
        if platform not in LONG_FORM_PLATFORMS:
            return
        specificity_markers = [
            "例えば",
            "具体的",
            "注意",
            "ステップ",
            "チェック",
            "選択肢",
            "弱点バンク",
            "模試",
            "フラッシュカード",
        ]
        count = sum(marker in content for marker in specificity_markers)
        report.checks["specificity_marker_count"] = count
        if count < 2:
            report.add_warning("正文缺少具体例、操作、注意点或产品专属信息。", 15)

    @staticmethod
    def _check_cross_platform_similarity(
        report: ContentQualityReport,
        content: str,
        comparison_contents: Iterable[str],
    ) -> None:
        normalized = re.sub(r"\s+", "", content)
        ratios = []
        for other in comparison_contents:
            candidate = re.sub(r"\s+", "", str(other or ""))
            if not normalized or not candidate:
                continue
            ratios.append(SequenceMatcher(None, normalized, candidate).ratio())
        highest = max(ratios, default=0.0)
        report.checks["highest_cross_platform_similarity"] = round(highest, 3)
        if highest >= 0.72:
            report.add_error("与同主题的其他平台文章高度相似，必须更换平台角度。", 30)
        elif highest >= 0.58:
            report.add_warning("与同主题的其他平台文章较为相似，建议增加平台专属信息。", 10)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    if parsed.netloc.lower() == "ukamiru.jp":
        parsed = parsed._replace(netloc="www.ukamiru.jp")
    return urlunsplit(parsed)
