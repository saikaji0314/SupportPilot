"""离线评审外围：不读取密钥、不请求外部模型。"""
from copy import deepcopy
import unittest
from supportpilot.trajectory import normalize_record
from supportpilot.eval_demo import run_review
from supportpilot.evaluation import RUBRIC, validate_review


def replay_record():
    return {"status": "completed", "input": {"user_text": "怎么处理？",
            "state": {"product_id": "demo", "checks": [], "status": "ongoing"},
            "passages": []}, "response": {"kind": "handoff", "text": "资料不足", "evidence_ids": []}}


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
            return {"items": [{"criterion_id": c["id"], "verdict": "unclear", "reason": "待核实"} for c in RUBRIC]}
        result = run_review(trace, model=object(), evaluator=judge)
        self.assertEqual(result["verdict_counts"], {"unclear": 3})


if __name__ == "__main__":
    unittest.main()
