from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityReport, UkamiruProductFacts


LONG_FORM_PLATFORMS = {"ameba", "hatena", "livedoor", "note", "zenn"}


@dataclass
class FactReviewReport:
    reviewer: str
    model: str
    decision: str
    score: int
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verified_claims: list[str] = field(default_factory=list)
    unverifiable_claims: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    facts_version: str = ""
    attempt: int = 0

    @property
    def approved(self) -> bool:
        return self.decision == "approved" and not self.blocking_errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "model": self.model,
            "decision": self.decision,
            "score": self.score,
            "blocking_errors": self.blocking_errors,
            "warnings": self.warnings,
            "verified_claims": self.verified_claims,
            "unverifiable_claims": self.unverifiable_claims,
            "source_ids": self.source_ids,
            "facts_version": self.facts_version,
            "attempt": self.attempt,
        }


class FactReviewService:
    def __init__(self, facts: UkamiruProductFacts | None = None) -> None:
        self.facts = facts or UkamiruProductFacts()
        self.reviewer_id = settings.fact_review_reviewer_id.strip() or "fact-review-bot-v1"
        self.model = settings.fact_review_model.strip() or settings.openai_model

    def should_review(self, *, topic: Topic, platform: str, title: str, content: str) -> bool:
        if not settings.fact_review_enabled:
            return False
        return (
            (settings.fact_review_all_long_form and platform.lower() in LONG_FORM_PLATFORMS)
            or self.facts.requires_manual_review(topic, title=title, content=content)
        )

    def review(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        topic: Topic,
        platform: str,
        quality_report: ContentQualityReport,
        attempt: int,
    ) -> FactReviewReport:
        if not settings.openai_api_key:
            return self._blocked_report("Fact reviewer API key is not configured.", attempt)

        try:
            payload = self._chat_json(
                system_prompt=self._review_system_prompt(),
                user_prompt=self._review_user_prompt(
                    title=title,
                    summary=summary,
                    content=content,
                    topic=topic,
                    platform=platform,
                    quality_report=quality_report,
                ),
                max_tokens=2500,
            )
            report = self._parse_report(payload, attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            return self._blocked_report(f"Fact reviewer failed safely: {exc}", attempt)

        if quality_report.publish_blocked:
            report.decision = "rewrite_required"
            report.blocking_errors = list(dict.fromkeys(report.blocking_errors + quality_report.errors))
        if report.score < settings.fact_review_min_score:
            report.decision = "rewrite_required"
            report.blocking_errors = list(
                dict.fromkeys(
                    report.blocking_errors
                    + [f"Fact review score {report.score} is below {settings.fact_review_min_score}."]
                )
            )

        known_source_ids = {str(item.get("id")) for item in self.editorial_sources()}
        unknown_sources = [item for item in report.source_ids if item not in known_source_ids]
        if unknown_sources:
            report.decision = "rewrite_required"
            report.blocking_errors.append(f"Unknown editorial source ids: {', '.join(unknown_sources)}")
        if self.requires_official_source(topic=topic, title=title, content=content) and not report.source_ids:
            report.decision = "rewrite_required"
            report.blocking_errors.append("Legal or regulatory content has no verified official source id.")
        if report.unverifiable_claims:
            report.decision = "rewrite_required"
            report.blocking_errors.append("Article contains claims that the reviewer could not verify.")
        report.blocking_errors = list(dict.fromkeys(report.blocking_errors))
        return report

    def rewrite(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        topic: Topic,
        platform: str,
        report: FactReviewReport,
    ) -> tuple[str, str, str]:
        payload = self._chat_json(
            system_prompt=(
                "You are a cautious Japanese content repair editor, separate from the original writer. "
                "Rewrite only what is needed to satisfy the fact review. Never invent a fact. "
                "Remove claims that are not directly supported by the supplied fact/source pack. "
                "Return JSON only with title, summary, and content. Preserve useful structure and links."
            ),
            user_prompt="\n".join(
                [
                    f"Platform: {platform}",
                    f"Topic: {topic.master_topic}",
                    f"Target keyword: {topic.target_keyword}",
                    "Verified fact/source pack:",
                    json.dumps(self._fact_pack(), ensure_ascii=False, indent=2),
                    "Review report:",
                    json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
                    "Original artifact:",
                    json.dumps(
                        {"title": title, "summary": summary, "content": content},
                        ensure_ascii=False,
                        indent=2,
                    ),
                ]
            ),
            max_tokens=max(settings.llm_max_tokens, 5000),
        )
        repaired_title = str(payload.get("title") or "").strip()
        repaired_summary = str(payload.get("summary") or "").strip()
        repaired_content = str(payload.get("content") or "").strip()
        if not repaired_title or not repaired_content:
            raise RuntimeError("Fact repair response did not include a title and content.")
        return repaired_title, repaired_summary, repaired_content

    def requires_official_source(self, *, topic: Topic, title: str, content: str) -> bool:
        text = " ".join([topic.master_topic, topic.topic_cluster, title, content])
        return any(str(term) in text for term in self.facts.data.get("legal_review_terms", []))

    def editorial_sources(self) -> list[dict[str, Any]]:
        return [item for item in self.facts.data.get("verified_editorial_sources", []) if isinstance(item, dict)]

    def _fact_pack(self) -> dict[str, Any]:
        return {
            "version": self.facts.version,
            "product_capabilities": self.facts.verified_capabilities(),
            "forbidden_product_claims": self.facts.forbidden_claim_patterns(),
            "editorial_facts": self.facts.verified_editorial_facts(),
            "official_sources": self.editorial_sources(),
        }

    def _review_system_prompt(self) -> str:
        return (
            "You are an independent Japanese fact-review bot. You did not write the article. "
            "Use only the supplied verified fact/source pack for product, legal, regulatory, date, "
            "statistics, and exam-system claims. Treat unsupported claims as unverifiable. "
            "Do not approve merely because prose sounds plausible. Return JSON only."
        )

    def _review_user_prompt(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        topic: Topic,
        platform: str,
        quality_report: ContentQualityReport,
    ) -> str:
        schema = {
            "decision": "approved | rewrite_required | blocked",
            "score": "integer 0-100",
            "blocking_errors": ["specific error"],
            "warnings": ["non-blocking issue"],
            "verified_claims": ["claim supported by the pack"],
            "unverifiable_claims": ["claim not supported by the pack"],
            "source_ids": ["only ids from official_sources"],
        }
        return "\n".join(
            [
                f"Platform: {platform}",
                f"Topic: {topic.master_topic}",
                f"Topic cluster: {topic.topic_cluster}",
                f"Target keyword: {topic.target_keyword}",
                "Required JSON schema:",
                json.dumps(schema, ensure_ascii=False, indent=2),
                "Verified fact/source pack:",
                json.dumps(self._fact_pack(), ensure_ascii=False, indent=2),
                "Deterministic quality report:",
                json.dumps(quality_report.as_dict(), ensure_ascii=False, indent=2),
                "Artifact:",
                json.dumps(
                    {"title": title, "summary": summary, "content": content},
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )

    def _chat_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
        base_url = settings.openai_base_url.rstrip("/")
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=360, trust_env=False) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Fact reviewer request failed: HTTP {response.status_code}: {response.text}")
        response_payload = response.json()
        choices = response_payload.get("choices") or []
        if not choices:
            raise RuntimeError("Fact reviewer response did not include choices.")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        parsed = json.loads(str(content))
        if not isinstance(parsed, dict):
            raise RuntimeError("Fact reviewer did not return a JSON object.")
        return parsed

    def _parse_report(self, payload: dict[str, Any], *, attempt: int) -> FactReviewReport:
        decision = str(payload.get("decision") or "blocked").strip().lower()
        if decision not in {"approved", "rewrite_required", "blocked"}:
            decision = "blocked"
        try:
            score = max(0, min(int(payload.get("score", 0)), 100))
        except (TypeError, ValueError):
            score = 0
        return FactReviewReport(
            reviewer=self.reviewer_id,
            model=self.model,
            decision=decision,
            score=score,
            blocking_errors=self._string_list(payload.get("blocking_errors")),
            warnings=self._string_list(payload.get("warnings")),
            verified_claims=self._string_list(payload.get("verified_claims")),
            unverifiable_claims=self._string_list(payload.get("unverifiable_claims")),
            source_ids=self._string_list(payload.get("source_ids")),
            facts_version=self.facts.version,
            attempt=attempt,
        )

    def _blocked_report(self, message: str, attempt: int) -> FactReviewReport:
        return FactReviewReport(
            reviewer=self.reviewer_id,
            model=self.model,
            decision="blocked",
            score=0,
            blocking_errors=[message],
            facts_version=self.facts.version,
            attempt=attempt,
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
