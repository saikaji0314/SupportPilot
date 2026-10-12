"""多轮记录核心：理解本轮反馈，再把变化合并进普通字典 State。"""

from typing import Literal
from copy import deepcopy
import json
from supportpilot.agent.prompts.feedback import FEEDBACK_PROMPT

from pydantic import BaseModel, Field


class FactUpdate(BaseModel):
    text: str = Field(min_length=1, description="用户明确提供的新事实或纠正后的事实，不写猜测原因")
    replaces: list[str] = Field(default_factory=list, description="被这条事实明确纠正的旧事实 ID；新增时为空")


class Feedback(BaseModel):
    facts: list[FactUpdate] = Field(default_factory=list)
    check_result: Literal["unknown", "not_done", "passed", "failed"] = Field(
        default="unknown",
        description="仅指 pending 检查：未说明、明确未做、检查条件符合/操作达到目的、检查条件不符/操作未达到目的",
    )
    issue_status: Literal["unknown", "ongoing", "resolved"] = Field(
        default="unknown", description="整个问题是否还存在；检查正常不等于问题恢复"
    )


def extract_feedback(model, *, user_text: str, state: dict) -> Feedback:
    """把本轮用户话和旧 State 给模型，只提取变化，不选择排障操作。

    key: model.with_structured_output(Feedback).invoke(messages)
    messages 组织
    """
    system_prompt = FEEDBACK_PROMPT
    user_prompt = json.dumps({"user_text": user_text, "state": state}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return model.with_structured_output(Feedback).invoke(messages)


def merge_feedback(state: dict, feedback: Feedback, *, message_id: str, user_text: str) -> dict:
    """复制 State，校验并合并事实、pending 检查反馈与问题状态。

    不调用模型、不检索、不选择下一步；返回新 State，不修改传入对象。
    新事实 ID 用 f'{message_id}-f{序号}'，来源写 source_message_id。
    非 unknown 的检查反馈只能更新 state['pending'] 对应的真实检查。
    示例见 examples/conversation/cases.json。
    """
    new_state = deepcopy(state)

    old_fact_ids = {fact["id"] for fact in new_state["facts"]}

    # facts
    replaced_facts = set()
    for fact in feedback.facts:
        for replace_fact in fact.replaces:
            if replace_fact not in old_fact_ids:
                raise ValueError(f"replace fact {replace_fact} 不存在")
            if replace_fact in replaced_facts:
                raise ValueError("不允许两条更新同一个fact")
            replaced_facts.add(replace_fact)
    # 先删除被纠正的旧事实，再判断新事实是否重复，避免同文字替换后事实消失。
    new_state["facts"] = [fact for fact in new_state["facts"] if fact["id"] not in replaced_facts]
    current_texts = {fact["text"] for fact in new_state["facts"]}
    for fact_idx, fact in enumerate(feedback.facts):
        if fact.text not in current_texts:
            fact_id = f"{message_id}-f{fact_idx+1}"
            if fact_id in old_fact_ids:
                raise ValueError(f"fact ID {fact_id} 已存在")
            new_state["facts"].append({
                "id": fact_id,
                "text": fact.text, 
                "source_message_id": message_id
            })
            current_texts.add(fact.text)

    # checks
    if feedback.check_result in ["not_done", "passed", "failed"]:
        matches = [check for check in new_state["checks"] if check["id"] == new_state["pending"]]
        if len(matches) != 1:
            raise ValueError(f"pending check {new_state['pending']} 必须唯一存在")
        check = matches[0]
        check["result"] = feedback.check_result
        check["feedback"] = user_text
        check["source_message_id"] = message_id
        if feedback.check_result != "not_done":
            new_state["pending"] = None

    # status
    if feedback.issue_status != "unknown":
        new_state["status"] = feedback.issue_status
    if feedback.issue_status == "resolved":
        new_state["pending"] = None

    return new_state
