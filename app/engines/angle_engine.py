from app.models.distribution_task import PlannedDistribution
from app.models.topic import Topic


class ContentAngleEngine:
    """Generates platform-specific angles for a topic."""

    ANGLE_MAP = {
        "note": "実務でつまずきやすい理由と解決手順",
        "ameba": "読者に寄り添うやさしい実務解説",
        "hatena": "SEOを意識した再利用しやすい解説テンプレート",
        "zenn": "実装手順と技術的な分解",
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
