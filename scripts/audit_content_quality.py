from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlmodel import Session, select

from app.db import engine
from app.models.artifact import ContentArtifact
from app.models.topic import Topic
from app.services.content_quality_service import ContentQualityService


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SEO and product-fact audit for generated content.")
    parser.add_argument("--platform", default="", help="Optional platform filter")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--published-only", action="store_true")
    args = parser.parse_args()

    quality = ContentQualityService()
    findings: list[dict[str, object]] = []
    with Session(engine) as session:
        statement = select(ContentArtifact).order_by(ContentArtifact.created_at.desc()).limit(args.limit)
        if args.platform:
            statement = statement.where(ContentArtifact.platform == args.platform.lower())
        if args.published_only:
            statement = statement.where(ContentArtifact.published == True)  # noqa: E712
        artifacts = list(session.exec(statement).all())

        for artifact in artifacts:
            topic = session.get(Topic, artifact.topic_id)
            if not topic:
                continue
            comparisons = list(
                session.exec(
                    select(ContentArtifact.content)
                    .where(ContentArtifact.topic_id == artifact.topic_id)
                    .where(ContentArtifact.id != artifact.id)
                    .where(ContentArtifact.platform != artifact.platform)
                ).all()
            )
            target_url = quality.facts.resolve_target_url(topic)
            report = quality.evaluate(
                title=artifact.artifact_title or "",
                content=artifact.content,
                topic=topic,
                platform=artifact.platform,
                target_url=target_url,
                comparison_contents=comparisons,
            )
            if not report.errors and not report.warnings:
                continue
            findings.append(
                {
                    "artifact_id": artifact.id,
                    "platform": artifact.platform,
                    "title": artifact.artifact_title,
                    "status": artifact.status,
                    "published_url": artifact.published_url,
                    "score": report.score,
                    "errors": report.errors,
                    "warnings": report.warnings,
                    "manual_review_required": quality.facts.requires_manual_review(
                        topic,
                        title=artifact.artifact_title or "",
                        content=artifact.content,
                    ),
                }
            )

    summary = Counter()
    for item in findings:
        summary["findings"] += 1
        summary[f"platform:{item['platform']}"] += 1
        if item["errors"]:
            summary["blocked"] += 1
        if item["manual_review_required"]:
            summary["manual_review_required"] += 1

    print(json.dumps({"summary": dict(summary), "items": findings}, ensure_ascii=False, indent=2))
    return 1 if summary["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
