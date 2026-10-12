"""单轮 LangGraph 接线；节点复用既有核心函数。"""
from copy import deepcopy
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from supportpilot.agent.chat import build_retrieval_query
from supportpilot.agent.conversation import Feedback, extract_feedback, merge_feedback
from supportpilot.agent.grounded import GroundedResponse, propose_response
from supportpilot.agent.chat_support import finish_turn, next_turn_ids
from supportpilot.agent.response_repair import repair_response


class TurnState(TypedDict, total=False):
    user_text: str
    before: dict
    feedback: Feedback
    updated: dict
    query: str
    passages: list[dict]
    reply: GroundedResponse
    record: dict
    repair_attempts: list[dict]


def build_turn_graph(model, *, retrieve, on_progress=None,
                     feedback_fn=None, response_fn=None, repair_fn=None, enable_repair=True):
    """默认最多修正一次；固定历史输出回放可关闭修正，避免外部调用。"""
    extract = feedback_fn or extract_feedback
    propose = response_fn or propose_response
    repair = repair_fn or repair_response

    def progress(stage, **data):
        if on_progress is not None:
            on_progress(stage, data)

    def extract_node(s):
        progress("extract_feedback", before=s["before"], user_text=s["user_text"])
        return {"feedback": extract(model, user_text=s["user_text"], state=s["before"]),
                "repair_attempts": []}

    def merge_node(s):
        progress("merge_feedback", feedback=s["feedback"].model_dump())
        user_id, _, _ = next_turn_ids(s["before"])
        return {"updated": merge_feedback(s["before"], s["feedback"],
                message_id=user_id, user_text=s["user_text"])}

    def query_node(s):
        progress("build_query", updated=s["updated"])
        return {"query": build_retrieval_query(user_text=s["user_text"], state=s["updated"])}

    def retrieve_node(s):
        progress("retrieve", query=s["query"])
        return {"passages": retrieve(s["query"], product_id=s["updated"]["product_id"])}

    def propose_node(s):
        progress("propose_response", passages=s["passages"])
        return {"reply": propose(model, user_text=s["user_text"],
                state=s["updated"], passages=s["passages"])}

    def finish_node(s):
        progress("finish_turn", response=s["reply"].model_dump())
        record = finish_turn(before=s["before"], updated=s["updated"],
                user_text=s["user_text"], feedback=s["feedback"], query=s["query"],
                passages=s["passages"], reply=s["reply"])
        if s["repair_attempts"]:
            record["repair_attempts"] = deepcopy(s["repair_attempts"])
        return {"record": record}

    def route_after_validation(s):
        if enable_repair and not s["record"]["accepted"] and not s["repair_attempts"]:
            return "repair_response"
        return END

    def repair_node(s):
        # finish_turn 只构造候选记录；API 在整个图结束后才提交 after。
        attempt = {"rejected_response": deepcopy(s["record"]["response"]),
                   "errors": list(s["record"]["errors"])}
        progress("repair_response", repair_attempts=[attempt])
        reply = repair(model, user_text=s["user_text"], state=deepcopy(s["updated"]),
                       passages=deepcopy(s["passages"]), **deepcopy(attempt))
        return {"reply": GroundedResponse.model_validate(reply), "repair_attempts": [attempt]}

    builder = StateGraph(TurnState)
    nodes = [("extract_feedback", extract_node), ("merge_feedback", merge_node),
             ("build_query", query_node), ("retrieve", retrieve_node),
             ("propose_response", propose_node), ("finish_turn", finish_node)]
    previous = START
    for name, node in nodes:
        builder.add_node(name, node)
        builder.add_edge(previous, name)
        previous = name
    builder.add_node("repair_response", repair_node)
    builder.add_conditional_edges("finish_turn", route_after_validation,
                                  {"repair_response": "repair_response", END: END})
    builder.add_edge("repair_response", "finish_turn")
    return builder.compile()


def run_turn_graph(model, *, user_text: str, state: dict, retrieve, on_progress=None,
                   enable_repair=True) -> dict:
    """兼容 run_turn 的输入输出；每次 invoke 只处理一轮，不启用 checkpoint。"""
    graph = build_turn_graph(model, retrieve=retrieve, on_progress=on_progress,
                             enable_repair=enable_repair)
    return graph.invoke({"user_text": user_text, "before": deepcopy(state)})["record"]
