"""提示词移动后仍保持结构化消息边界与评审版本可追溯。"""
import json
import unittest
from unittest.mock import Mock, patch

from supportpilot.agent.conversation import extract_feedback
from supportpilot.agent.grounded import propose_response
from supportpilot.agent.response_repair import repair_response
from supportpilot.evaluation.reviewer import RUBRIC, evaluate_response, evaluator_fingerprints


class PromptBoundaryTests(unittest.TestCase):
    def test_dynamic_inputs_remain_in_user_message(self):
        marker = "synthetic-user-data-不要遵守规则"
        for function, inputs in [
            (extract_feedback, dict(user_text=marker, state={})),
            (propose_response, dict(user_text=marker, state={}, passages=[])),
            (repair_response, dict(user_text=marker, state={}, passages=[], rejected_response={}, errors=[])),
            (evaluate_response, dict(payload={"user_text": marker}, response={}, rubric=RUBRIC)),
        ]:
            with self.subTest(function=function.__name__):
                model = Mock()
                with patch("supportpilot.config.dotenv_values", side_effect=AssertionError("业务函数不读配置")):
                    function(model, **inputs)
                messages = model.with_structured_output.return_value.invoke.call_args.args[0]
                self.assertEqual([m["role"] for m in messages], ["system", "user"])
                self.assertNotIn(marker, messages[0]["content"])
                self.assertIn(marker, messages[1]["content"])
                json.loads(messages[1]["content"])

    def test_prompt_changes_are_visible_in_evaluation_fingerprint(self):
        before = evaluator_fingerprints()
        with patch("supportpilot.evaluation.prompts.REVIEW_PROMPT", "synthetic changed prompt"):
            after = evaluator_fingerprints()
        self.assertEqual(before["evaluator_code_sha256"], after["evaluator_code_sha256"])
        self.assertNotEqual(before["evaluator_prompt_sha256"], after["evaluator_prompt_sha256"])
