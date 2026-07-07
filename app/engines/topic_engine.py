from app.models.topic import TopicCreate


class TopicEngine:
    def normalize_topic(self, payload: TopicCreate) -> TopicCreate:
        payload.master_topic = payload.master_topic.strip()
        payload.topic_cluster = payload.topic_cluster.strip()
        payload.business_goal = payload.business_goal.strip()
        payload.target_keyword = payload.target_keyword.strip()
        if payload.secondary_keyword:
            payload.secondary_keyword = payload.secondary_keyword.strip()
        payload.secondary_keywords = [item.strip() for item in payload.secondary_keywords if item.strip()]
        if payload.target_audience:
            payload.target_audience = payload.target_audience.strip()
        if payload.article_type:
            payload.article_type = payload.article_type.strip()
        if payload.content_focus:
            payload.content_focus = payload.content_focus.strip()
        payload.scenes = [item.strip() for item in payload.scenes if item.strip()]
        if payload.target_url:
            payload.target_url = payload.target_url.strip()
        if payload.brand_name:
            payload.brand_name = payload.brand_name.strip()
        if payload.site:
            payload.site = payload.site.strip()
        if payload.language:
            payload.language = payload.language.strip()
        if payload.extra_rules:
            payload.extra_rules = payload.extra_rules.strip()
        payload.target_platforms = [platform.strip().lower() for platform in payload.target_platforms]
        if payload.note_account:
            payload.note_account = payload.note_account.strip()
        if payload.feishu_record_id:
            payload.feishu_record_id = payload.feishu_record_id.strip()
        if payload.feishu_topic_id:
            payload.feishu_topic_id = payload.feishu_topic_id.strip()
        return payload
