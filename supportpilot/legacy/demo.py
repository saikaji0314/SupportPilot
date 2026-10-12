"""固定反馈演示：不调用模型，不读取 .env。"""

from supportpilot.legacy.state import SessionState
from supportpilot.legacy.core import merge_observation, choose_next_action


evidence_by_id = {
    "internet_status_read": {
        "title": "查看 Internet IP 状态",
        "summary": "请在路由器管理页面查看 Internet/WAN 的 IP 地址，告诉我是 0.0.0.0、不是 0.0.0.0，还是无法判断。不同界面的菜单名称可能不同。",
        "source_url": "https://www.tp-link.com/us/support/faq/1556/",
    },
    "zero_ip_check_cable": {
        "title": "Internet IP 为 0.0.0.0 时的连接检查",
        "summary": "请检查上游设备与路由器 WAN 口之间的网线是否连接牢固，再反馈能否上网；无法完成检查也可以直接告诉我。",
        "source_url": "https://www.tp-link.com/us/support/faq/1556/",
    },
}

observations = [
    {"wifi_connected": True},
    {"others_affected": True, "setup_complete": True, "mode": "router"},
    {"wan_status": "zero"},
    {"check_results": {"check_wan_cable": "failed"}},
]


def run_demo() -> None:
    session = SessionState()
    for turn, observation in enumerate(observations, start=1):
        session = merge_observation(session, observation)

        # WAN 答案存在 wan_status；网线检查答案存在 check_results。
        # 收到答案后不再等待，但答案本身仍保留在状态里。
        if session.pending_check == "internet_status" and session.wan_status is not None:
            session.pending_check = None
        elif session.pending_check in session.check_results:
            session.pending_check = None
        if session.restored:
            session.pending_check = None

        action = choose_next_action(session, evidence_by_id)
        print(f"\n第 {turn} 轮（合成反馈）: {observation}")
        print(f"助手 [{action.kind}]: {action.text}")
        for evidence_id in action.evidence_ids:
            evidence = evidence_by_id[evidence_id]
            print(f"依据: {evidence['title']} — {evidence['source_url']}")

        # 先选动作，再由驱动记录本轮发出的检查。
        if action.kind == "recommend_check":
            session.pending_check = action.check_id
        if action.kind in ("resolved", "handoff"):
            break


if __name__ == "__main__":
    run_demo()
