"""Ragas 离线适配：只读取保存的输入和回复，不重新检索或生成客服回复。"""
import asyncio
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version, PackageNotFoundError
import json
import math
import os
from pathlib import Path

from supportpilot.config import load_chat_config

RAGAS_VERSION = "0.4.3"
INPUT_VERSION = "conversation-context-v1"
METRICS = ("faithfulness", "context_utilization")
METRIC_TIMEOUT = 120


def prepare_sample(trace: dict) -> dict:
    """映射固定快照；事实/历史只帮助解释问题，不能混进资料正文。"""
    if not trace.get("reviewable"):
        return {"status": "skipped_incomplete", "reason": "记录中断或缺少完整输入/回复。"}
    response = trace["response"]
    if response.get("kind") not in ("answer", "recommend_check"):
        return {"status": "not_applicable", "reason": "本轮是追问、恢复确认或转人工，不套用回答类 RAG 分数。"}
    payload = trace["payload"]
    passages = payload.get("passages")
    if not isinstance(passages, list) or not passages:
        return {"status": "missing_data", "reason": "本轮没有检索正文，不能把无资料解释为 0 分或满分。"}
    if any(not isinstance(p, dict) or not isinstance(p.get("text"), str) or not p["text"].strip()
           for p in passages):
        return {"status": "missing_data", "reason": "存在缺失正文的片段，未静默删块或补找资料。"}
    if not isinstance(response.get("text"), str) or not response["text"].strip():
        return {"status": "missing_data", "reason": "候选回复缺少正文。"}
    state = payload.get("state")
    if not isinstance(state, dict) or not isinstance(payload.get("user_text"), str) or not payload["user_text"].strip():
        return {"status": "missing_data", "reason": "缺少问题或会话状态。"}
    question = {"user_text": payload["user_text"],
                "product_id": state.get("product_id"),
                "facts": state.get("facts", []), "checks": state.get("checks", []),
                "pending": state.get("pending"), "messages": state.get("messages", [])}
    sample = {"user_input": json.dumps(question, ensure_ascii=False),
              "response": response["text"], "retrieved_contexts": [p["text"] for p in passages]}
    return {"status": "ready", "input_version": INPUT_VERSION,
            "context_scope": "generation_passages_including_preceding_context",
            "context_ids": [p.get("id") for p in passages], "sample": sample,
            "input_sha256": sha256(json.dumps(sample, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def _metric_result(name, value) -> dict:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"name": name, "status": "error", "value": None, "error_type": "InvalidScore"}
    if not math.isfinite(value):
        return {"name": name, "status": "undefined", "value": None,
                "reason": "指标未产生有限数值（例如未抽取到可评估陈述），不计入有效分数。"}
    if not 0 <= value <= 1:
        return {"name": name, "status": "error", "value": None, "error_type": "InvalidScore"}
    return {"name": name, "status": "completed", "value": float(value)}


class RagasScorer:
    """同步任务入口；每轮在同一个事件循环中创建并关闭异步客户端。"""
    def __init__(self):
        # 在导入 SDK 前禁用其匿名使用遥测，不连接 Ragas 托管平台。
        os.environ["RAGAS_DO_NOT_TRACK"] = "true"
        actual = version("ragas")
        if actual != RAGAS_VERSION:
            raise ValueError("UnsupportedRagasVersion")
        self.config = load_chat_config()
        if not self.config.api_key:
            raise ValueError("MissingModelConfiguration")
        self.metadata = {"ragas_version": actual, "model": self.config.model,
                         "metric_timeout_seconds": METRIC_TIMEOUT,
                         "request_timeout_seconds": self.config.timeout,
                         "sdk_retries": 0, "structured_output_attempts": 1}

    async def _score(self, sample):
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import Faithfulness, ContextUtilization
        async with AsyncOpenAI(api_key=self.config.api_key, base_url=self.config.base_url,
                               timeout=self.config.timeout, max_retries=0) as client:
            llm = llm_factory(self.config.model, client=client, max_retries=1, max_tokens=4096)
            results = []
            for name, metric in [("faithfulness", Faithfulness(llm=llm)),
                                 ("context_utilization", ContextUtilization(llm=llm))]:
                try:
                    score = await asyncio.wait_for(metric.ascore(**sample), timeout=METRIC_TIMEOUT)
                    results.append(_metric_result(name, score.value))
                except Exception as exc:
                    # 不存服务返回正文、提示词回显或密钥；另一指标仍可独立完成。
                    results.append({"name": name, "status": "error", "value": None,
                                    "error_type": type(exc).__name__})
            return results

    def score(self, sample: dict) -> list[dict]:
        return asyncio.run(self._score(sample))


def run_ragas(trace: dict, *, scorer_factory=RagasScorer) -> dict:
    """CLI/管理端共享；只有适用且输入齐全时才初始化 SDK 和模型客户端。"""
    prepared = prepare_sample(trace)
    result = {"evaluator": "ragas", "expected_ragas_version": RAGAS_VERSION,
              "metric_names": list(METRICS), "adapter_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "metrics": [], **prepared}
    if prepared["status"] != "ready":
        return result
    try:
        scorer = scorer_factory()
        result.update(scorer.metadata)
        result["metrics"] = scorer.score(deepcopy(prepared["sample"]))
        statuses = [item["status"] for item in result["metrics"]]
        result["status"] = ("completed" if statuses and all(s == "completed" for s in statuses)
                            else "partial" if "completed" in statuses else "error")
    except (PackageNotFoundError, ModuleNotFoundError) as exc:
        result.update(status="unavailable", error_type=type(exc).__name__,
                      reason="Ragas 依赖未安装完整，请安装 requirements-ragas.txt。")
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__)
    return result
