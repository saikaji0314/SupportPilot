"""连续对话实验；默认展示说明，--chat 才连接嵌入、索引与聊天模型。"""

from supportpilot.paths import ROOT
import argparse
import json
from pathlib import Path
from uuid import uuid4
from time import monotonic

from supportpilot.agent.chat import run_turn
from supportpilot.agent.chat_support import make_retriever, new_state



def save_turn(folder: Path, attempt: int, record: dict):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"turn-{attempt:02d}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "examples/rag/source.json").read_text(encoding="utf-8"))
    state = new_state(config["product_id"])
    if not args.chat:
        print("本次只预览，不请求服务；核心接口已实现。")
        print("流程：反馈提取 → 合并 State → 构建查询 → 检索正文 → 模型回复 → 校验和记录")
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print("运行 python -m supportpilot.cli.chat_demo --chat；输入 /exit 退出。")
        return
    from supportpilot.providers.bailian import bailian

    retrieve = make_retriever()
    model = bailian()
    folder = ROOT / ".local/chat" / uuid4().hex[:12]
    print(f"记录目录：{folder}\n每次启动为新会话；输入 /exit 退出，最多 12 次输入。")
    for attempt in range(1, 13):
        try:
            user_text = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_text == "/exit":
            break
        if not user_text:
            continue
        started = monotonic()
        partial = {"user_text": user_text, "before": state, "status": "running"}
        labels = {"extract_feedback": "理解反馈", "merge_feedback": "合并记录",
                  "build_query": "构建检索文本", "retrieve": "检索资料",
                  "propose_response": "生成回复", "finish_turn": "校验并记录"}

        def on_progress(stage, data):
            partial.update(data)
            partial.update(stage=stage, elapsed_seconds=round(monotonic() - started, 2))
            save_turn(folder, attempt, partial)
            print(f"处理中：{labels[stage]}……", flush=True)

        try:
            record = run_turn(model, user_text=user_text, state=state, retrieve=retrieve,
                              on_progress=on_progress)
        except NotImplementedError as exc:
            print(str(exc))
            break
        except KeyboardInterrupt:
            partial.update(status="interrupted", elapsed_seconds=round(monotonic() - started, 2))
            save_turn(folder, attempt, partial)
            print("\n本轮已中断，中间结果已保存，旧状态保留。")
            break
        except Exception as exc:
            partial.update(status="error", error_type=type(exc).__name__,
                           elapsed_seconds=round(monotonic() - started, 2))
            save_turn(folder, attempt, partial)
            print(f"本轮未完成：{labels.get(partial.get('stage'), '运行')} / {type(exc).__name__}；"
                  "停止会话，中间结果已保存。")
            break
        save_turn(folder, attempt, record)
        if not record["accepted"]:
            print("本轮候选回复未通过校验：" + "；".join(record["errors"]))
            print("候选回复和中间结果已保存，旧状态保留；停止本次实验。")
            break
        state = record["after"]
        print(f"助手 [{record['response']['kind']}]：{record['response']['text']}")
        cited = set(record["response"]["evidence_ids"])
        for passage in record["passages"]:
            if passage["id"] in cited:
                print(f"来源：{passage['id']} | PDF 页 {passage.get('page', '?')} | {passage['source_url']}")
        if record["response"]["kind"] in ("resolved", "handoff"):
            print("本次会话结束；handoff 只表示建议人工接手，并未提交工单。")
            break


if __name__ == "__main__":
    main()
