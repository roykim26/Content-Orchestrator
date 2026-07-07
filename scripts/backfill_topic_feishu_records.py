from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine
from app.models.topic import Topic
from app.services.feishu_topic_sync_service import FeishuTopicSyncService


def fields_from_topic(topic: Topic) -> dict[str, object]:
    fields: dict[str, object] = {
        "master_topic": topic.master_topic,
        "topic_cluster": topic.topic_cluster,
        "business_goal": topic.business_goal,
        "target_keyword": topic.target_keyword,
        "secondary_keyword": topic.secondary_keyword or "",
        "secondary_keywords": topic.secondary_keywords,
        "target_audience": topic.target_audience or "",
        "article_type": topic.article_type or "",
        "content_focus": topic.content_focus or "",
        "scenes": topic.scenes,
        "target_url": topic.target_url or "",
        "brand_name": topic.brand_name or "",
        "site": topic.site or "",
        "language": topic.language or "",
        "extra_rules": topic.extra_rules or "",
        "priority": topic.priority,
        "target_platforms": topic.target_platforms,
        "status": topic.status,
        "brief": topic.brief or "",
        "note_account": topic.note_account or "",
    }
    return {key: value for key, value in fields.items() if value not in ("", [], None)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    with Session(engine) as session:
        service = FeishuTopicSyncService(session)
        for topic_id in args.topic_id:
            topic = session.exec(select(Topic).where(Topic.id == topic_id)).first()
            if not topic:
                results.append({"topic_id": topic_id, "status": "missing"})
                continue
            if topic.feishu_record_id:
                results.append(
                    {
                        "topic_id": topic.id,
                        "status": "skipped",
                        "feishu_record_id": topic.feishu_record_id,
                    }
                )
                continue
            if args.dry_run:
                results.append(
                    {
                        "topic_id": topic.id,
                        "status": "preview",
                        "master_topic": topic.master_topic,
                    }
                )
                continue

            created = service.create_topic_record(fields_from_topic(topic))
            topic.feishu_record_id = str(created.get("record_id") or "") or None
            session.add(topic)
            session.commit()
            results.append(
                {
                    "topic_id": topic.id,
                    "status": "created",
                    "feishu_record_id": topic.feishu_record_id,
                    "written_fields": created.get("written_fields", []),
                }
            )

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
