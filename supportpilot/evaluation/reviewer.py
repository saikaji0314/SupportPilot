"""离线语义评审契约；不参与客服在线决策。"""
from typing import Literal
from hashlib import sha256
from pathlib import Path
from pydantic import BaseModel, Field
import json
from supportpilot.evaluation.prompts import build_review_prompt

RUBRIC = [
    {"id": "grounding", "criterion": "产品事实和操作是否被引用正文支持；资料不足时是否避免编造？"},
    {"id": "preconditions", "criterion": "操作所需前提是否由当前事实确认，而非把默认值当成现状？"},
    {"id": "history", "criterion": "是否尊重纠正与检查历史，避免无解释重复和一次多个独立检查？"},
]


def evaluator_fingerprints() -> dict[str, str]:
    """分别记录评审实现与系统提示词/标准的版本，供 CLI 和管理端共用。"""
    prompt = build_review_prompt(RUBRIC)
    return {
        "evaluator_code_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluator_prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
    }


class RequiredCondition(BaseModel):
    condition: str = Field(min_length=1, description="资料说明的操作必要条件")
    source_refs: list[str] = Field(min_length=1, description="支持该条件的资料位置")


class ConfirmedFact(BaseModel):
    fact: str = Field(min_length=1, description="用户当前已确认的事实，不含资料默认值或助手推测")
    source_refs: list[str] = Field(min_length=1, description="本轮用户反馈或 state.facts 的位置")


class PreconditionsAudit(BaseModel):
    required_conditions: list[RequiredCondition]
    confirmed_facts: list[ConfirmedFact]
    missing_conditions: list[str] = Field(description="尚未被用户当前事实确认的必要条件；已确认则为空")
    candidate_behavior: Literal["direct_action", "clarify", "no_conditional_action"] = Field(
        description="直接要求执行条件性操作、先询问条件、或没有条件性操作/判断"
    )


class ReviewItem(BaseModel):
    criterion_id: str
    audit: PreconditionsAudit | None = Field(
        default=None, description="preconditions 必须填写，先列条件/当前事实/缺项再给结论；其他项填 null"
    )
    verdict: Literal["pass", "fail", "unclear", "not_applicable"]
    reason: str = Field(min_length=1)
    support_refs: list[str] = Field(default_factory=list)


class ResponseReview(BaseModel):
    items: list[ReviewItem]


def evaluate_response(model, *, payload: dict, response: dict,
                      rubric: list[dict]) -> ResponseReview:
    """逐项评审候选回复，返回结论与证据位置，不修改输入。

    payload = {user_text, state: 已合并状态, passages: 正文快照}。
    只把 payload/response/rubric 交给评审模型，不传人工标签。
    每条标准返回一个 ReviewItem；缺依据用 unclear；不适用用 not_applicable。
    key: model.with_structured_output(ResponseReview).invoke(messages)
    具体任务及提示词边界见 .local/下一阶段-轨迹与评测.md。
    """
    system_prompt = build_review_prompt(rubric)
    user_prompt = json.dumps(
        {"payload": payload, "response": response}, ensure_ascii=False
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return model.with_structured_output(ResponseReview).invoke(messages)


def validate_review(review, rubric: list[dict]) -> ResponseReview:
    """防止裁判漏项/重复项被报告误算为通过；不验证其语义判断。"""
    review = ResponseReview.model_validate(review)
    ids = [item.criterion_id for item in review.items]
    expected = [item["id"] for item in rubric]
    if len(ids) != len(expected) or set(ids) != set(expected):
        raise ValueError("评审必须恰好覆盖每个 criterion_id 一次")
    return review


def review_consistency_errors(review: ResponseReview) -> list[str]:
    """只检查裁判显式输出的矛盾/缺项，不保证条件和事实抽取正确。"""
    errors = []
    for item in review.items:
        if item.criterion_id != "preconditions":
            continue
        if item.audit is None:
            errors.append("preconditions 缺少 audit，前提评审无法核对")
        elif item.audit.candidate_behavior == "direct_action":
            if not item.audit.required_conditions:
                errors.append("前提审计不完整：直接要求条件性操作，却未列出 required_conditions")
            if item.audit.missing_conditions and item.verdict == "pass":
                errors.append("评审自相矛盾：存在未确认的必要条件且直接要求操作，却判为 pass")
    return errors
