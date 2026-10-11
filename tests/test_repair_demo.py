from copy import deepcopy
import unittest

from supportpilot.chat_support import new_state
from supportpilot.grounded import GroundedResponse
from supportpilot.repair_demo import run_repair


class RepairDemoTests(unittest.TestCase):
    def test_failed_repair_stops_after_one_call_and_preserves_input(self):
        payload = {"user_text": "测试问题", "state": new_state("sample"),
                   "passages": [], "rejected_response": {}, "errors": ["缺少引用"]}
        before = deepcopy(payload)
        calls = []
        def repair(model, **data):
            calls.append(data)
            data["state"]["status"] = "resolved"
            return GroundedResponse(kind="answer", text="仍然没有引用", evidence_ids=[])
        result = run_repair(None, payload, repair_fn=repair)
        self.assertFalse(result["accepted"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(payload, before)

    def test_valid_candidate_skips_model(self):
        result = run_repair(None, {"errors": []}, repair_fn=lambda *a, **kw: self.fail("不应调用"))
        self.assertEqual(result["status"], "skipped")

    def test_supported_repair_passes(self):
        payload = {"user_text": "测试问题", "state": new_state("sample"),
                   "passages": [{"id": "p1", "product_ids": ["sample"], "text": "测试事实"}],
                   "rejected_response": {}, "errors": ["错误引用"]}
        result = run_repair(None, payload, repair_fn=lambda *a, **kw:
            GroundedResponse(kind="answer", text="测试事实", evidence_ids=["p1"]))
        self.assertTrue(result["accepted"])
