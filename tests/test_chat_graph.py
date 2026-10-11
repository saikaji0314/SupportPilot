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
                options = {"enable_repair": False} if runner is run_turn_graph else {}
                outputs.append(runner(None, user_text="合成反馈", state=state, retrieve=retrieve, **options,
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

    def test_repair_success_or_rejection_is_bounded(self):
        bad = GroundedResponse(kind="recommend_check", text="检查", evidence_ids=["missing"])
        good = GroundedResponse(kind="recommend_check", text="检查", evidence_ids=["p1"])
        for corrected, accepted in [(good, True), (bad, False)]:
            with self.subTest(accepted=accepted):
                state = new_state("demo")
                events, calls = [], []
                def repair(model, **data):
                    calls.append(deepcopy(data))
                    data["state"]["facts"].clear()
                    return corrected
                graph = build_turn_graph(None,
                    retrieve=lambda *a, **kw: [{"id": "p1", "product_ids": ["demo"]}],
                    feedback_fn=lambda *a, **kw: Feedback(facts=[{"text": "新增事实"}]),
                    response_fn=lambda *a, **kw: bad, repair_fn=repair,
                    on_progress=lambda stage, data: events.append(stage))
                record = graph.invoke({"before": state, "user_text": "问题"})["record"]
                self.assertEqual(record["accepted"], accepted)
                self.assertEqual(len(calls), 1)
                self.assertEqual(events.count("retrieve"), 1)
                self.assertEqual(events.count("merge_feedback"), 1)
                self.assertEqual(events[-3:], ["finish_turn", "repair_response", "finish_turn"])
                self.assertEqual(record["repair_attempts"][0]["rejected_response"], bad.model_dump())
                self.assertEqual(state, new_state("demo"))
                if accepted:
                    self.assertEqual(len(record["after"]["messages"]), 2)
                    self.assertEqual(len(record["after"]["checks"]), 1)
                    self.assertEqual(len(record["after"]["facts"]), 1)
                else:
                    self.assertEqual(record["after"], state)

    def test_valid_reply_never_calls_repair(self):
        graph = build_turn_graph(None, retrieve=lambda *a, **kw: [],
            feedback_fn=lambda *a, **kw: Feedback(),
            response_fn=lambda *a, **kw: GroundedResponse(kind="ask_user", text="具体情况？"),
            repair_fn=lambda *a, **kw: self.fail("不应修正"))
        self.assertTrue(graph.invoke({"before": new_state("demo"), "user_text": "问题"})["record"]["accepted"])


if __name__ == "__main__":
    unittest.main()
