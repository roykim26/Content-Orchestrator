import unittest

from app.engines.distribution_engine import DistributionEngine
from app.models.topic import Topic


class DistributionEngineTest(unittest.TestCase):
    def test_build_plan_skips_livedoor_while_it_is_not_integrated(self) -> None:
        topic = Topic(
            id="topic_without_livedoor",
            master_topic="Test topic",
            topic_cluster="test",
            business_goal="test",
            target_keyword="test",
            target_platforms=["note", "livedoor", "x"],
        )

        plans = DistributionEngine().build_plan(topic)

        self.assertEqual([plan.platform for plan in plans], ["note", "x"])

    def test_build_plan_creates_no_task_for_livedoor_only_topic(self) -> None:
        topic = Topic(
            id="topic_livedoor_only",
            master_topic="Test topic",
            topic_cluster="test",
            business_goal="test",
            target_keyword="test",
            target_platforms=["livedoor"],
        )

        plans = DistributionEngine().build_plan(topic)

        self.assertEqual(plans, [])


if __name__ == "__main__":
    unittest.main()
