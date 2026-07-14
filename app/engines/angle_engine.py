from app.models.distribution_task import PlannedDistribution
from app.models.topic import Topic


class ContentAngleEngine:
    """Generates platform-specific angles for a topic."""

    ANGLE_MAP = {
        "note": "学習設計やプロダクト思想を掘り下げる事例・ストーリー",
        "ameba": "一つの具体的な学習場面を描く使用体験・学習日記",
        "hatena": "一つの長尾検索意図を解決する試験別の具体的SEOガイド",
        "livedoor": "更新情報または範囲を絞った短い実用チュートリアル",
        "zenn": "実装判断、データ設計、学習UXの技術的な分解",
        "x": "今日すぐ共有できる3つの要点",
        "bluesky": "議論を生みやすい問題提起型の切り口",
        "ppt": "運用担当者向けのスライド型プレイブック",
        "quora": "悩みに直接答えるQ&A型の切り口",
        "short_video": "冒頭の引きを重視した短尺解説台本",
    }

    def build_angle(self, topic: Topic, plan: PlannedDistribution) -> str:
        return self.ANGLE_MAP.get(
            plan.platform,
            f"{topic.master_topic} for {plan.platform}",
        )
