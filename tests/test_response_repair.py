from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from supportpilot.agent.chat_support import new_state
from supportpilot.agent.grounded import GroundedResponse
from supportpilot.agent.response_repair import repair_response


class ResponseRepairTests(unittest.TestCase):
    def payload(self):
        return {
            "user_text": "管理页面如何登录？",
            "state": new_state("sample"),
            "passages": [{"id": "p1", "product_ids": ["sample"],
                          "text": "连接设备网络后打开管理页面。"}],
            "rejected_response": {"kind": "answer", "text": "打开管理页面。",
                                  "evidence_ids": ["invalid"]},
            "errors": ["引用不属于本轮检索：invalid"],
        }

    def test_model_receives_complete_context_without_mutating_inputs(self):
        payload = self.payload()
        before = deepcopy(payload)
        model = Mock()
        expected = GroundedResponse(kind="answer", text="打开管理页面。", evidence_ids=["p1"])
        model.with_structured_output.return_value.invoke.return_value = expected
        self.assertIs(repair_response(model, **payload), expected)
        model.with_structured_output.assert_called_once_with(GroundedResponse)
        invoke = model.with_structured_output.return_value.invoke
        invoke.assert_called_once()
        messages = invoke.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(json.loads(messages[1]["content"]), before)
        self.assertEqual(payload, before)

    def test_timeout_propagates_without_another_model_call(self):
        model = Mock()
        invoke = model.with_structured_output.return_value.invoke
        invoke.side_effect = TimeoutError("test timeout")
        with self.assertRaises(TimeoutError):
            repair_response(model, **self.payload())
        invoke.assert_called_once()
