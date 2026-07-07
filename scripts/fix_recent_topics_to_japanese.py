from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine
from app.models.distribution_task import DistributionTask
from app.models.topic import Topic
from app.services.feishu_topic_sync_service import FeishuTopicSyncService


TOPIC_FIXES = {
    "topic_c8cb39255798": {
        "master_topic": "宅建AIのコンテンツ運用を自動化する基本ワークフロー",
        "target_keyword": "宅建AI コンテンツ運用 自動化",
        "secondary_keyword": "宅建AI コンテンツ運用",
        "secondary_keywords": ["宅建AI コンテンツ運用", "宅建AI 自動化"],
        "target_audience": "宅建学習者、不動産会社の実務担当者、AI活用を検討するコンテンツ運用担当者",
        "article_type": "実務ハウツー",
        "content_focus": "宅建AI.jp向けに、日々のテーマ設計から記事配信までを日本語で実務的に整理する",
        "scenes": ["宅建学習", "コンテンツ運用", "AI自動化"],
        "brief": "宅建AI.jp向けに自動補充した日本語テーマ。宅建学習と不動産AI活用に沿って、コンテンツ運用の基本手順を解説する。",
    },
    "topic_301361485243": {
        "master_topic": "不動産AIで見込み客獲得を効率化するワークフロー",
        "target_keyword": "不動産AI 見込み客獲得 ワークフロー",
        "secondary_keyword": "不動産AI 見込み客獲得",
        "secondary_keywords": ["不動産AI 見込み客獲得", "不動産営業 AI"],
        "target_audience": "不動産会社の営業担当者、マーケティング担当者、宅建AI.jpの読者",
        "article_type": "実務ハウツー",
        "content_focus": "不動産AIを使った見込み客獲得、問い合わせ導線、営業フォローを日本語で整理する",
        "scenes": ["不動産営業", "見込み客獲得", "AIワークフロー"],
        "brief": "宅建AI.jp向けに自動補充した日本語テーマ。不動産AIを活用した見込み客獲得の流れを実務目線で解説する。",
    },
    "topic_a3c50cc3a969": {
        "master_topic": "宅建AIの記事をSEO流入につなげる配信テンプレート",
        "target_keyword": "宅建AI SEO 記事配信",
        "secondary_keyword": "宅建AI SEO",
        "secondary_keywords": ["宅建AI SEO", "宅建AI 記事配信"],
        "target_audience": "宅建AI.jpのSEO担当者、不動産領域のコンテンツ運用担当者",
        "article_type": "SEOチェックリスト",
        "content_focus": "宅建AIの記事を検索流入、内部リンク、外部配信に接続する方法を日本語で整理する",
        "scenes": ["SEO設計", "記事配信", "被リンク獲得"],
        "brief": "宅建AI.jp向けに自動補充した日本語テーマ。宅建AI記事をSEO流入につなげる配信テンプレートを解説する。",
    },
    "topic_8d7ee42e61b0": {
        "master_topic": "不動産AIメディアのプログラマティックSEO運用手順",
        "target_keyword": "不動産AI プログラマティックSEO",
        "secondary_keyword": "不動産AI SEO",
        "secondary_keywords": ["不動産AI SEO", "プログラマティックSEO 不動産"],
        "target_audience": "不動産AIメディアのSEO担当者、宅建AI.jpの運用担当者",
        "article_type": "SEO運用ガイド",
        "content_focus": "不動産AI領域で大量の検索意図を整理し、記事群として運用する手順を日本語で解説する",
        "scenes": ["プログラマティックSEO", "不動産AI", "記事群設計"],
        "brief": "宅建AI.jp向けに自動補充した日本語テーマ。不動産AIメディアで使えるプログラマティックSEO運用手順を解説する。",
    },
    "topic_014afeb10f21": {
        "master_topic": "宅建学習コンテンツを複数媒体に展開する再利用システム",
        "target_keyword": "宅建 学習コンテンツ 再利用",
        "secondary_keyword": "宅建 学習コンテンツ",
        "secondary_keywords": ["宅建 学習コンテンツ", "宅建 コンテンツ再利用"],
        "target_audience": "宅建学習コンテンツを運用する担当者、宅建AI.jpの編集担当者",
        "article_type": "運用プレイブック",
        "content_focus": "宅建学習記事をnote、Ameba、Hatena、SNSなどへ再利用する流れを日本語で整理する",
        "scenes": ["宅建学習", "コンテンツ再利用", "複数媒体展開"],
        "brief": "宅建AI.jp向けに自動補充した日本語テーマ。宅建学習コンテンツを複数媒体に展開する再利用システムを解説する。",
    },
}

ANGLE_BY_PLATFORM = {
    "note": "実務でつまずきやすい理由と解決手順",
    "ameba": "読者に寄り添うやさしい実務解説",
    "hatena": "SEOを意識した再利用しやすい解説テンプレート",
    "zenn": "実装手順と技術的な分解",
    "x": "今日すぐ共有できる3つの要点",
    "bluesky": "議論を生みやすい問題提起型の切り口",
    "livedoor": "検索読者向けのわかりやすい実務解説",
}


def main() -> None:
    results: list[dict[str, object]] = []
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        feishu = FeishuTopicSyncService(session)
        for topic_id, fix in TOPIC_FIXES.items():
            topic = session.exec(select(Topic).where(Topic.id == topic_id)).first()
            if not topic:
                results.append({"topic_id": topic_id, "status": "missing"})
                continue

            for field_name, value in fix.items():
                setattr(topic, field_name, value)
            topic.language = "ja"
            topic.site = "takkenai.jp"
            topic.updated_at = now
            session.add(topic)

            tasks = session.exec(select(DistributionTask).where(DistributionTask.topic_id == topic_id)).all()
            task_updates = 0
            for task in tasks:
                task.angle = ANGLE_BY_PLATFORM.get(task.platform, f"{topic.master_topic}の実務解説")
                task.updated_at = now
                session.add(task)
                task_updates += 1

            written_fields: list[str] = []
            if topic.feishu_record_id:
                written_fields = feishu.update_record_fields(
                    topic.feishu_record_id,
                    {
                        "master_topic": topic.master_topic,
                        "target_keyword": topic.target_keyword,
                        "target_audience": topic.target_audience,
                        "article_type": topic.article_type,
                        "content_focus": topic.content_focus,
                        "scenes": topic.scenes,
                        "site": topic.site,
                        "language": topic.language,
                        "brief": topic.brief,
                    },
                )

            results.append(
                {
                    "topic_id": topic_id,
                    "status": "updated",
                    "master_topic": topic.master_topic,
                    "target_keyword": topic.target_keyword,
                    "task_updates": task_updates,
                    "feishu_record_id": topic.feishu_record_id,
                    "feishu_written_fields": written_fields,
                }
            )

        session.commit()

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
