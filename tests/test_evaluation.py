"""离线评审外围：不读取密钥、不请求外部模型。"""
from copy import deepcopy
import unittest
from supportpilot.trajectory import normalize_record, render_trace
from supportpilot.eval_demo import run_review
from supportpilot.evaluation import RUBRIC, validate_review


def replay_record():
    return {"status": "completed", "input": {"user_text": "怎么处理？",
            "state": {"product_id": "demo", "checks": [], "status": "ongoing"},
            "passages": []}, "response": {"kind": "handoff", "text": "资料不足", "evidence_ids": []}}


def audited_review(*, behavior="clarify", missing=None, verdict="pass"):
    return {"items": [{"criterion_id": c["id"], "verdict": verdict, "reason": "合成评审",
                       "audit": {"required_conditions": [{"condition": "满足操作前提", "source_refs": ["passages.p1"]}],
                                 "confirmed_facts": [], "missing_conditions": missing or [],
                                 "candidate_behavior": behavior} if c["id"] == "preconditions" else None}
                      for c in RUBRIC]}


class EvaluationTests(unittest.TestCase):
    def test_replay_does_not_imply_accepted(self):
        raw = replay_record()
        before = deepcopy(raw)
        trace = normalize_record(raw, record_id="r1")
        self.assertIsNone(trace["accepted"])
        self.assertEqual(trace["scope"], "response_replay")
        self.assertEqual(raw, before)
        self.assertEqual(run_review(trace)["judge_status"], "not_run")

    def test_timeout_never_uses_original_response(self):
        raw = replay_record()
        raw["original_response"] = raw.pop("response")
        raw["status"] = "error"
        trace = normalize_record(raw, record_id="r2")
        self.assertIsNone(trace["response"])
        result = run_review(trace, model=object(), evaluator=lambda *a, **k: self.fail("不应调用"))
        self.assertEqual(result["judge_status"], "skipped_incomplete")
        self.assertIsNone(result["rules"]["errors"])

    def test_rejected_candidate_can_be_reviewed(self):
        r = replay_record()
        trace = normalize_record({"accepted": False, "user_text": "问题", "before": {},
            "updated": r["input"]["state"], "passages": [], "response": r["response"],
            "errors": ["合成拒绝"], "after": {}}, record_id="r3")
        self.assertTrue(trace["reviewable"])
        self.assertFalse(trace["accepted"])

    def test_incomplete_turn_is_not_success(self):
        trace = normalize_record({"before": {}, "user_text": "问题", "status": "running"}, record_id="r4")
        self.assertFalse(trace["reviewable"])
        self.assertIn("state", trace["missing"])

    def test_duplicate_judge_items_rejected(self):
        item = {"criterion_id": RUBRIC[0]["id"], "verdict": "pass", "reason": "合成"}
        with self.assertRaises(ValueError):
            validate_review({"items": [item] * 3}, RUBRIC)

    def test_judge_failure_separate_from_rules(self):
        trace = normalize_record(replay_record(), record_id="r5")
        def fail(*a, **kw):
            raise TimeoutError("private upstream text")
        result = run_review(trace, model=object(), evaluator=fail)
        self.assertEqual(result["rules"]["errors"], [])
        self.assertEqual(result["judge_status"], "error")
        self.assertNotIn("private", str(result))

    def test_judge_counts_unclear_separately(self):
        trace = normalize_record(replay_record(), record_id="r6")
        def judge(*a, **kw):
            return audited_review(verdict="unclear")
        result = run_review(trace, model=object(), evaluator=judge)
        self.assertEqual(result["verdict_counts"], {"unclear": 3})

    def test_contradictory_pass_is_preserved_but_not_counted(self):
        trace = normalize_record(replay_record(), record_id="r7")
        result = run_review(trace, model=object(), evaluator=lambda *a, **kw:
                            audited_review(behavior="direct_action", missing=["未确认的条件"]))
        self.assertEqual(result["judge_status"], "invalid_review")
        self.assertNotIn("verdict_counts", result)
        self.assertEqual(result["review"]["items"][1]["verdict"], "pass")
        self.assertIn("自相矛盾", result["review_errors"][0])
        report = render_trace(trace, result)
        self.assertIn('"missing_conditions"', report)
        self.assertIn('"invalid_review"', report)

    def test_clarification_with_missing_conditions_can_pass(self):
        trace = normalize_record(replay_record(), record_id="r8")
        result = run_review(trace, model=object(), evaluator=lambda *a, **kw:
                            audited_review(missing=["未确认的条件"]))
        self.assertEqual(result["judge_status"], "completed")
        self.assertEqual(result["verdict_counts"], {"pass": 3})

    def test_missing_conditions_with_fail_is_consistent(self):
        trace = normalize_record(replay_record(), record_id="r9")
        result = run_review(trace, model=object(), evaluator=lambda *a, **kw:
                            audited_review(behavior="direct_action", missing=["未确认的条件"], verdict="fail"))
        self.assertEqual(result["judge_status"], "completed")
        self.assertEqual(result["review_errors"], [])

    def test_confirmed_conditions_can_pass(self):
        raw = audited_review(behavior="direct_action")
        raw["items"][1]["audit"]["confirmed_facts"] = [
            {"fact": "用户确认操作前提", "source_refs": ["state.facts.f1"]}]
        result = run_review(normalize_record(replay_record(), record_id="r10"),
                            model=object(), evaluator=lambda *a, **kw: raw)
        self.assertEqual(result["judge_status"], "completed")

    def test_missing_audit_is_not_silently_counted(self):
        raw = audited_review()
        raw["items"][1].pop("audit")
        result = run_review(normalize_record(replay_record(), record_id="r11"),
                            model=object(), evaluator=lambda *a, **kw: raw)
        self.assertEqual(result["judge_status"], "invalid_review")
        self.assertIsNone(result["review"]["items"][1]["audit"])
        self.assertNotIn("verdict_counts", result)

    def test_nonconditional_reply_still_supplies_empty_audit(self):
        raw = audited_review(behavior="no_conditional_action", verdict="not_applicable")
        raw["items"][1]["audit"]["required_conditions"] = []
        result = run_review(normalize_record(replay_record(), record_id="r12"),
                            model=object(), evaluator=lambda *a, **kw: raw)
        self.assertEqual(result["judge_status"], "completed")

    def test_correct_fail_with_empty_audit_is_still_incomplete(self):
        raw = audited_review(behavior="direct_action", verdict="fail")
        raw["items"][1]["audit"]["required_conditions"] = []
        result = run_review(normalize_record(replay_record(), record_id="r13"),
                            model=object(), evaluator=lambda *a, **kw: raw)
        self.assertEqual(result["judge_status"], "invalid_review")
        self.assertEqual(result["review"]["items"][1]["verdict"], "fail")
        self.assertNotIn("verdict_counts", result)
        self.assertIn("required_conditions", result["review_errors"][0])


if __name__ == "__main__":
    unittest.main()
