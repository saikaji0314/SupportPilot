from copy import deepcopy
import unittest
from unittest.mock import patch

from supportpilot.chat import run_turn
from supportpilot.chat_graph import run_turn_graph, build_turn_graph
from supportpilot.chat_support import new_state
from supportpilot.conversation import Feedback
from supportpilot.grounded import GroundedResponse


class ChatGraphTests(unittest.TestCase):
    def compare(self, feedback, reply, passages):
        state = new_state("demo")
        original = deepcopy(state)
        outputs, events, calls = [], [], []
        for target, runner in [("supportpilot.chat", run_turn), ("supportpilot.chat_graph", run_turn_graph)]:
            stages, queries = [], []
            def retrieve(query, product_id):
                queries.append((query, product_id))
                return deepcopy(passages)
            with patch(target + ".extract_feedback", return_value=feedback), patch(target + ".propose_response", return_value=reply):
                outputs.append(runner(None, user_text="合成反馈", state=state, retrieve=retrieve,
                    on_progress=lambda stage, data: stages.append((stage, deepcopy(data)))))
            events.append(stages)
            calls.append(queries)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(events[0], events[1])
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(state, original)
        return outputs[1]

    def test_accepted_check_matches_python_pipeline(self):
        record = self.compare(Feedback(facts=[{"text": "无法连接"}]),
            GroundedResponse(kind="recommend_check", text="合成检查", evidence_ids=["p1"]),
            [{"id": "p1", "text": "合成资料", "product_ids": ["demo"]}])
        self.assertTrue(record["accepted"])
        self.assertEqual(record["after"]["pending"], "c1")

    def test_rejected_response_does_not_commit_feedback(self):
        record = self.compare(Feedback(facts=[{"text": "新增事实"}]),
            GroundedResponse(kind="answer", text="合成无效引用", evidence_ids=["missing"]), [])
        self.assertFalse(record["accepted"])
        self.assertEqual(record["after"], record["before"])

    def test_resolved_matches_python_pipeline(self):
        record = self.compare(Feedback(issue_status="resolved"),
            GroundedResponse(kind="resolved", text="已恢复"), [])
        self.assertEqual(record["after"]["status"], "resolved")

    def test_timeout_propagates_without_mutating_input(self):
        state = new_state("demo")
        original = deepcopy(state)
        with patch("supportpilot.chat_graph.extract_feedback", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                run_turn_graph(None, user_text="问题", state=state, retrieve=lambda *a, **kw: [])
        self.assertEqual(state, original)

    def test_compiled_graph_can_handle_independent_inputs(self):
        graph = build_turn_graph(None, retrieve=lambda *a, **kw: [],
            feedback_fn=lambda *a, **kw: Feedback(),
            response_fn=lambda *a, **kw: GroundedResponse(kind="handoff", text="缺资料"))
        a = graph.invoke({"user_text": "A", "before": new_state("a")})["record"]
        b = graph.invoke({"user_text": "B", "before": new_state("b")})["record"]
        self.assertEqual(b["after"]["product_id"], "b")
        self.assertEqual(len(b["after"]["messages"]), 2)
        self.assertEqual(a["after"]["messages"][0]["text"], "A")


if __name__ == "__main__":
    unittest.main()
