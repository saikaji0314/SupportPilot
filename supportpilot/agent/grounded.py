"""资料驱动回复：结合用户反馈、会话记录与本轮检索正文提出回复。"""

from typing import Literal
import json
from supportpilot.agent.prompts.response import RESPONSE_PROMPT
from pydantic import BaseModel, Field


class GroundedResponse(BaseModel):
    """模型本轮的输出。evidence_ids 引用传入资料的 id。"""

    kind: Literal[
        "answer",
        "ask_user",
        "recommend_check",
        "resolved",
        "handoff",
    ] = Field(
        description=(
            "回复类型，按本轮主要目的选择：解释事实用 answer；"
            "请求必要信息用 ask_user；要求执行检查用 recommend_check；"
            "用户明确报告恢复才用 resolved；资料不足以继续或需要人工接手用 handoff。"
            "回复含事实解释和检查时，用 recommend_check"
        ),
    )

    text: str = Field(
        min_length=1,
        description="回复文本",
    )

    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "引用的资料 id 列表，"
            "只能填写本轮 passages 中的 id 字段，"
            "不能填写 source_url、文档标题或自行生成的编号"
        ),
    )


def propose_response(model, *, user_text: str, state: dict, passages: list[dict]) -> GroundedResponse:
    """根据问题、会话与资料提出回复，不修改 state。

    组织通用系统提示词与输入，调用模型的结构化输出接口。
    不按产品名、WAN 值或案例编号选择固定答案。
    模型由调用方传入，本函数不创建客户端或读取配置。
    """
    system_prompt = RESPONSE_PROMPT
    user_prompt = json.dumps({"user_text": user_text, "state": state, "passages": passages}, ensure_ascii=False)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}]
    response = model.with_structured_output(GroundedResponse).invoke(messages)
    return response
