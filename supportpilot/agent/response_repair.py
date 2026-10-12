"""受限候选修正；由图控制调用次数和再次校验。"""
import json
from supportpilot.agent.prompts.repair import REPAIR_PROMPT

from supportpilot.agent.grounded import GroundedResponse


def repair_response(model, *, user_text: str, state: dict, passages: list[dict],
                    rejected_response: dict, errors: list[str]) -> GroundedResponse:
    """根据原输入、被拒绝的候选及程序错误，生成一个新的候选。

    不修改 state，不重新检索，不自行循环。返回完整 GroundedResponse。
    调用次数和再次校验由外围控制。实现说明见本地当前任务文档。
    """
    system_prompt = REPAIR_PROMPT
    user_prompt = json.dumps({
        "user_text": user_text,
        "state": state,
        "passages": passages,
        "rejected_response": rejected_response,
        "errors": errors,
    }, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return model.with_structured_output(GroundedResponse).invoke(messages)
