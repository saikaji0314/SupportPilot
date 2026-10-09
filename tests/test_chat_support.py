"""外围记录的关键边界；不请求模型、嵌入或 Chroma。"""

from copy import deepcopy
import unittest

from supportpilot.chat_support import finish_turn, new_state
from supportpilot.conversation import FactUpdate, Feedback, merge_feedback
from supportpilot.grounded import GroundedResponse


class ChatSupportTests(unittest.TestCase):
    def setUp(self):
        self.state = new_state("product")
        self.passages = [{"id": "p1", "text": "合成检查说明", "product_ids": ["product"]}]

    def finish(self, before, updated, reply, feedback=None):
        return finish_turn(before=before, updated=updated, user_text="合成反馈",
                           feedback=feedback or Feedback(), query="问题上下文",
                           passages=self.passages, reply=reply)

    def test_record_check_then_link_feedback_and_preserve_history(self):
        original = deepcopy(self.state)
        reply = GroundedResponse(kind="recommend_check", text="请确认测试条件是否正常。", evidence_ids=["p1"])
        first = self.finish(self.state, self.state, reply)
        self.assertTrue(first["accepted"])
        self.assertEqual(self.state, original)
        self.assertEqual(first["after"]["pending"], "c1")
        feedback = Feedback(check_result="passed", issue_status="ongoing")
        updated = merge_feedback(first["after"], feedback, message_id="u2", user_text="条件正常，问题还在")
        second = self.finish(first["after"], updated,
                             GroundedResponse(kind="ask_user", text="请补充当前现象。"), feedback)
        self.assertTrue(second["accepted"])
        self.assertEqual(second["after"]["checks"][0]["result"], "passed")
        self.assertIsNone(second["after"]["pending"])
        self.assertEqual([m["id"] for m in second["after"]["messages"]], ["u1", "a1", "u2", "a2"])

    def test_invalid_citation_preserves_old_state_and_candidate(self):
        updated = deepcopy(self.state)
        updated["facts"] = [{"id": "u1-f1", "text": "新事实", "source_message_id": "u1"}]
        reply = GroundedResponse(kind="answer", text="候选回答", evidence_ids=["invented"])
        result = self.finish(self.state, updated, reply)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["after"], self.state)
        self.assertEqual(result["updated"], updated)
        self.assertEqual(result["response"]["text"], "候选回答")

    def test_wrong_product_and_exact_repeat_are_rejected(self):
        reply = GroundedResponse(kind="recommend_check", text="检查条件。", evidence_ids=["p1"])
        self.passages[0]["product_ids"] = ["other"]
        self.assertFalse(self.finish(self.state, self.state, reply)["accepted"])
        self.passages[0]["product_ids"] = ["product"]
        first = self.finish(self.state, self.state, reply)["after"]
        self.assertFalse(self.finish(first, first, reply)["accepted"])

    def test_resolution_requires_report_and_keeps_unknown_check_unknown(self):
        reply = GroundedResponse(kind="resolved", text="收到，问题已恢复。")
        self.assertFalse(self.finish(self.state, self.state, reply)["accepted"])
        self.state["checks"] = [{"id": "c1", "text": "测试", "result": "unknown"}]
        self.state["pending"] = "c1"
        feedback = Feedback(issue_status="resolved")
        updated = merge_feedback(self.state, feedback, message_id="u1", user_text="好了")
        result = self.finish(self.state, updated, reply, feedback)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["after"]["checks"][0]["result"], "unknown")
        self.assertIsNone(result["after"]["pending"])

    def test_same_text_replacement_does_not_erase_fact(self):
        self.state["facts"] = [{"id": "u1-f1", "text": "条件正常", "source_message_id": "u1"}]
        feedback = Feedback(facts=[FactUpdate(text="条件正常", replaces=["u1-f1"])])
        updated = merge_feedback(self.state, feedback, message_id="u2", user_text="确认条件正常")
        self.assertEqual(updated["facts"], [{"id": "u2-f1", "text": "条件正常", "source_message_id": "u2"}])
        self.assertEqual(self.state["facts"][0]["id"], "u1-f1")

    def test_repeated_message_id_cannot_duplicate_fact_id(self):
        self.state["facts"] = [{"id": "u1-f1", "text": "条件甲", "source_message_id": "u1"}]
        with self.assertRaises(ValueError):
            merge_feedback(self.state, Feedback(facts=[FactUpdate(text="条件乙")]),
                           message_id="u1", user_text="新内容")


if __name__ == "__main__":
    unittest.main()
