"""Ragas 输入、失败语义与实际 SDK 接线；不读取真实配置、不请求外部服务。"""
from copy import deepcopy
from importlib.util import find_spec
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from supportpilot.config import ChatConfig
from supportpilot.evaluation.trajectory import normalize_record, render_trace
from supportpilot.evaluation.ragas_adapter import prepare_sample, run_ragas, _metric_result
from supportpilot.evaluation.service import run_ragas_review


def trace():
    return normalize_record({"status": "completed", "input": {
        "user_text": "还是不行，下一步呢？", "state": {"product_id": "synthetic-product",
        "facts": [{"id": "f1", "text": "已完成初始设置"}], "checks": [],
        "pending": None, "messages": [{"role": "user", "text": "无法进入管理页面"}]},
        "passages": [{"id": "p1", "text": "The button opens the setup page.",
                      "product_ids": ["synthetic-product"]}]},
        "response": {"kind": "answer", "text": "The button opens the setup page.", "evidence_ids": ["p1"]}},
        record_id="synthetic-ragas")


class RagasTests(unittest.TestCase):
    def test_input_keeps_context_order_and_history_separate(self):
        t = trace()
        t["payload"]["passages"].insert(0, {"id": "previous", "text": "Preceding context."})
        before = deepcopy(t)
        sample = prepare_sample(t)
        self.assertEqual(sample["sample"]["retrieved_contexts"], ["Preceding context.", "The button opens the setup page."])
        self.assertEqual(sample["context_ids"], ["previous", "p1"])
        question = json.loads(sample["sample"]["user_input"])
        self.assertIn("已完成初始设置", str(question["facts"]))
        self.assertNotIn("已完成初始设置", str(sample["sample"]["retrieved_contexts"]))
        self.assertEqual(t, before)
        self.assertNotIn("reference", sample["sample"])

    def test_unsuitable_and_missing_inputs_do_not_create_scorer(self):
        for kind in ("ask_user", "resolved", "handoff"):
            t = trace(); t["response"]["kind"] = kind
            factory = Mock(side_effect=AssertionError("不能调用"))
            self.assertEqual(run_ragas(t, scorer_factory=factory)["status"], "not_applicable")
            factory.assert_not_called()
        t = trace(); t["payload"]["passages"] = []
        self.assertEqual(run_ragas(t, scorer_factory=Mock(side_effect=AssertionError()))["status"], "missing_data")
        t["reviewable"] = False
        self.assertEqual(run_ragas(t)["status"], "skipped_incomplete")

    def test_blank_context_is_not_silently_removed(self):
        t = trace(); t["payload"]["passages"].append({"id": "bad", "text": " "})
        self.assertEqual(prepare_sample(t)["status"], "missing_data")

    def test_zero_score_is_valid_and_nan_is_not_zero(self):
        self.assertEqual(_metric_result("faithfulness", 0)["value"], 0.0)
        self.assertEqual(_metric_result("faithfulness", 0)["status"], "completed")
        for value in (float("nan"), float("inf")):
            result = _metric_result("faithfulness", value)
            self.assertEqual(result["status"], "undefined")
            self.assertIsNone(result["value"])
            json.dumps(result, allow_nan=False)
        for value in (True, 1.2, "1"):
            self.assertEqual(_metric_result("faithfulness", value)["status"], "error")

    def test_partial_metric_results_and_no_raw_exception_message(self):
        scorer = Mock(metadata={"model": "synthetic"})
        scorer.score.return_value = [_metric_result("faithfulness", .5),
            {"name": "context_utilization", "status": "error", "value": None, "error_type": "TimeoutError"}]
        result = run_ragas(trace(), scorer_factory=lambda: scorer)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["metrics"][0]["value"], .5)
        result = run_ragas(trace(), scorer_factory=Mock(side_effect=TimeoutError("synthetic-secret")))
        self.assertEqual(result["status"], "error")
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_optional_dependency_failure_is_reported(self):
        result = run_ragas(trace(), scorer_factory=Mock(side_effect=ModuleNotFoundError("private path")))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private path", json.dumps(result))

    def test_shared_service_and_markdown_keep_numeric_results_separate(self):
        result = {"status": "completed", "metrics": [_metric_result("faithfulness", .5)]}
        with patch("supportpilot.evaluation.ragas_adapter.run_ragas", return_value=result):
            report = run_ragas_review(trace())
        self.assertEqual(report["judge_status"], "not_run")
        self.assertNotIn("verdict_counts", report)
        self.assertIn('faithfulness', render_trace(trace(), report))


@unittest.skipUnless(find_spec("ragas"), "可选 SDK 集成验证需安装 requirements-ragas.txt")
class RagasSdkTests(unittest.TestCase):
    def test_real_metrics_and_instructor_with_mock_http(self):
        import httpx
        from openai import AsyncOpenAI
        answers = [{"statements": ["The button opens the setup page."]},
                   {"statements": [{"statement": "The button opens the setup page.",
                                    "reason": "Supported by the context.", "verdict": 1}]},
                   {"reason": "The context supports the answer.", "verdict": 1}]
        calls = []
        def handle(request):
            calls.append(json.loads(request.content))
            answer = answers[len(calls)-1]
            return httpx.Response(200, json={"id": "synthetic-completion", "object": "chat.completion",
                "created": 0, "model": "synthetic-model", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": json.dumps(answer)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})
        class FakeClient(AsyncOpenAI):
            def __init__(self, **kwargs):
                super().__init__(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        with patch("supportpilot.evaluation.ragas_adapter.load_chat_config",
                   return_value=ChatConfig(api_key="synthetic", base_url="https://example.invalid/v1", model="synthetic-model")), \
             patch("openai.AsyncOpenAI", FakeClient), \
             patch("requests.post", side_effect=AssertionError("不能外发遥测")):
            result = run_ragas(trace())
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(calls), 3)
        self.assertEqual([m["name"] for m in result["metrics"]], ["faithfulness", "context_utilization"])
        self.assertTrue(all(m["value"] > .99 for m in result["metrics"]))
        self.assertTrue(all(c["response_format"]["type"] == "json_object" for c in calls))
        self.assertTrue(all(c["model"] == "synthetic-model" for c in calls))

    def test_sdk_metric_timeout_keeps_other_metric(self):
        async def slow_metric(**kwargs):
            await asyncio.sleep(1)
        # SDK 已启用遥测关闭设置；模型工厂只创建对象，ascore 使用替身。
        with patch("supportpilot.evaluation.ragas_adapter.load_chat_config",
                   return_value=ChatConfig(api_key="synthetic", base_url="https://example.invalid/v1", model="synthetic-model")), \
             patch("supportpilot.evaluation.ragas_adapter.METRIC_TIMEOUT", .01), \
             patch("ragas.metrics.collections.Faithfulness.ascore", side_effect=slow_metric), \
             patch("ragas.metrics.collections.ContextUtilization.ascore", new_callable=AsyncMock,
                   return_value=SimpleNamespace(value=0.0)), \
             patch("requests.post", side_effect=AssertionError("不能外发遥测")):
            result = run_ragas(trace())
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(result["metrics"][0]["error_type"], "TimeoutError")
        self.assertEqual(result["metrics"][1]["status"], "completed")
        self.assertEqual(result["metrics"][1]["value"], 0.0)
