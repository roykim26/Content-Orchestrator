from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from sqlmodel import Session, SQLModel, create_engine

from app.services.topic_refill_service import TopicRefillService


class TopicRefillQualityTests(unittest.TestCase):
    def test_one_topic_uses_only_one_long_form_platform(self) -> None:
        database = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(database)
        with Session(database) as session:
            service = TopicRefillService(session)
            service.signal_service = Mock()
            service.signal_service.resolve_keywords_for_strategy.return_value = [
                SimpleNamespace(
                    keyword="独学 資格試験 問題演習",
                    target_platforms=[],
                    source_details=[],
                    source_names=["test"],
                    score=10,
                )
            ]
            strategy = {
                "goal_weights": {"module_activation": 20},
                "priority_weights": {"S": 20},
                "strategies": [
                    {
                        "topic_cluster": "exam_module_launch",
                        "business_goal": "module_activation",
                        "priority": "S",
                        "target_platforms": ["ameba", "hatena", "note", "x", "bluesky"],
                        "title_templates": ["Ukamiruの新モジュールで{keyword}を始める手順"],
                        "target_url": "https://www.ukamiru.jp/",
                    }
                ],
            }
            refill_config = {"enabled": True, "status": "ready"}
            deficits = {"ameba": 5, "hatena": 12, "note": 8, "x": 5, "bluesky": 5}

            candidates = service._build_candidates(strategy, refill_config, deficits, set())

            self.assertEqual(len(candidates), 1)
            long_form = {"ameba", "hatena", "livedoor", "note", "zenn"}
            selected_long_form = long_form.intersection(candidates[0].target_platforms)
            self.assertEqual(selected_long_form, {"hatena"})
            self.assertNotIn("新モジュール", candidates[0].master_topic)
            self.assertIn("確認済み製品事実", candidates[0].extra_rules)


if __name__ == "__main__":
    unittest.main()
