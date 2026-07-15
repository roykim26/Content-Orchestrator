from app.models.distribution_task import PlannedDistribution
from app.models.topic import Topic


class DistributionEngine:
    DISABLED_PLATFORMS = {"livedoor"}

    CONTENT_TYPE_MAP = {
        "note": ("article", "brand_awareness"),
        "ameba": ("article", "brand_awareness"),
        "hatena": ("article", "seo_backlink"),
        "zenn": ("technical_article", "technical_authority"),
        "x": ("short_post", "traffic_reach"),
        "bluesky": ("discussion_post", "community_discussion"),
        "livedoor": ("article", "owned_media_distribution"),
        "ppt": ("slides", "asset_repackaging"),
        "quora": ("answer", "search_capture"),
        "short_video": ("script", "short_form_distribution"),
    }

    def build_plan(self, topic: Topic) -> list[PlannedDistribution]:
        plans: list[PlannedDistribution] = []
        for platform in topic.target_platforms:
            if platform in self.DISABLED_PLATFORMS:
                continue
            content_type, objective = self.CONTENT_TYPE_MAP.get(
                platform,
                ("article", "distribution"),
            )
            plans.append(
                PlannedDistribution(
                    platform=platform,
                    content_type=content_type,
                    objective=objective,
                )
            )
        return plans
