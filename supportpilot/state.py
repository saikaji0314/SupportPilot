from typing import Literal
from dataclasses import dataclass, field


@dataclass
class SessionState:
    # 当前设备是否已经连接到路由器的 Wi-Fi；None 表示尚未确认。
    wifi_connected: bool | None = None
    # 同一网络中的其他设备是否也受到影响；None 表示尚未询问或确认。
    others_affected: bool | None = None
    # 路由器是否已经完成初始设置；None 表示尚未确认。
    setup_complete: bool | None = None
    # 当前工作模式：router 为路由模式，ap 为接入点模式；None 表示未知。
    mode: Literal["router", "ap"] | None = None
    # 用户看到的 WAN/Internet 状态：zero 表示 IP 为 0.0.0.0，
    # nonzero 表示不是 0.0.0.0，unknown 表示用户无法判断；None 表示尚未查看。
    wan_status: Literal["zero", "nonzero", "unknown"] | None = None
    # 用户是否明确反馈问题已经恢复；首版默认 False，表示尚未恢复或尚未确认。
    restored: bool = False
    # 最近推荐且正在等待用户反馈的检查，例如 check_wan_cable。
    pending_check: str | None = None
    # 已执行检查及其结果，例如 {"check_wan_cable": "failed"}。
    check_results: dict[str, str] = field(default_factory=dict)
    # 用户原始消息，用于保留上下文和生成后续总结。
    user_messages: list[str] = field(default_factory=list)


@dataclass
class Action:
    kind: Literal["ask_user", "recommend_check", "resolved", "handoff"]
    # 本轮展示给用户的文字
    text: str
    # 这项检查的稳定标识，用于跟踪执行结果
    check_id: str | None = None
    # 支撑本轮建议的文档片段标识
    evidence_ids: list[str] = field(default_factory=list)
