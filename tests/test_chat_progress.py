"""验证一轮中断时能够定位阶段；使用合成模型与检索，不请求服务。"""

from copy import deepcopy
import unittest
from unittest.mock import patch

from supportpilot.chat import run_turn
from supportpilot.chat_support import new_state, with_preceding_context
from supportpilot.conversation import Feedback
from supportpilot.grounded import GroundedResponse


class ChatProgressTests(unittest.TestCase):
    def test_reply_timeout_keeps_feedback_query_passages_and_old_state(self):
        state = new_state("product")
        original = deepcopy(state)
        progress = {}

        def on_progress(stage, data):
            progress.update(data)
            progress["stage"] = stage

        passages = [{"id": "p1", "text": "合成资料", "product_ids": ["product"]}]
        with patch("supportpilot.chat.extract_feedback", return_value=Feedback()), \
             patch("supportpilot.chat.propose_response", side_effect=TimeoutError("private response")):
            with self.assertRaises(TimeoutError):
                run_turn(object(), user_text="问题", state=state,
                         retrieve=lambda query, product_id: passages, on_progress=on_progress)
        self.assertEqual(progress["stage"], "propose_response")
        self.assertIn("feedback", progress)
        self.assertIn("updated", progress)
        self.assertIn("query", progress)
        self.assertEqual(progress["passages"], passages)
        self.assertEqual(state, original)

    def test_feedback_timeout_is_identifiable_without_fake_changes(self):
        progress = {}

        def on_progress(stage, data):
            progress.update(data)
            progress["stage"] = stage

        with patch("supportpilot.chat.extract_feedback", side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                run_turn(object(), user_text="问题", state=new_state("product"),
                         retrieve=None, on_progress=on_progress)
        self.assertEqual(progress["stage"], "extract_feedback")
        self.assertNotIn("feedback", progress)

    def test_success_still_records_and_accepts_a_turn(self):
        reply = GroundedResponse(kind="ask_user", text="请补充现象。")
        stages = []
        with patch("supportpilot.chat.extract_feedback", return_value=Feedback()), \
             patch("supportpilot.chat.propose_response", return_value=reply):
            result = run_turn(object(), user_text="问题", state=new_state("product"),
                              retrieve=lambda query, product_id: [],
                              on_progress=lambda stage, data: stages.append(stage))
        self.assertTrue(result["accepted"])
        self.assertEqual(len(result["after"]["messages"]), 2)
        self.assertEqual(stages, ["extract_feedback", "merge_feedback", "build_query",
                                  "retrieve", "propose_response", "finish_turn"])

    def test_preceding_chunk_recovers_condition_without_crossing_product(self):
        def chunk(identifier, document, product, section, text):
            return {"id": identifier, "text": text, "metadata": {
                "document_id": document, "product_id": product, "source_url": "https://example.test/manual",
                "page": 1, "section": section}}

        chunks = [chunk("p0", "doc", "product", 0, "只有条件 A 成立时，"),
                  chunk("p1", "doc", "product", 1, "才执行操作 B。"),
                  chunk("other", "doc", "other-product", 0, "其他产品内容")]
        hit = {"id": "p1", "text": "才执行操作 B。", "product_ids": ["product"], "distance": 0.2}
        original = deepcopy(chunks)
        result = with_preceding_context([hit], chunks, "product")
        self.assertEqual([p["id"] for p in result], ["p0", "p1"])
        self.assertEqual(result[0]["text"], "只有条件 A 成立时，")
        self.assertEqual(result[1]["distance"], 0.2)
        self.assertEqual(chunks, original)


if __name__ == "__main__":
    unittest.main()
