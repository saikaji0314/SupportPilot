from supportpilot.state import SessionState, Action


def merge_observation(state: SessionState, patch: dict) -> SessionState:
    """在原状态上合并明确反馈；缺失字段和 None 保留旧值。"""
    for key, value in patch.items():
        if value is not None:
            if isinstance(value, dict):
                old_value = getattr(state, key)
                old_value.update(value)
                setattr(state, key, old_value)
            elif isinstance(value, list):
                old_value = getattr(state, key)
                old_value.extend(value)
                setattr(state, key, old_value)
            else:
                setattr(state, key, value)
    return state


def choose_next_action(state: SessionState, evidence_by_id: dict[str, dict]) -> Action:
    """每轮从头判断，返回一个动作；这里不修改会话状态。"""
    # 1. 已经恢复就结束，不再追问或检查。
    if state.restored:
        return Action(kind="resolved", text="你反馈网络已经恢复，本次排障结束。")

    # 2. 已知不适用时直接转交，不必问完其余字段。
    if state.wifi_connected is False:
        return Action(kind="handoff", text="当前版本只处理已连接 Wi-Fi 但无法上网的情况，请转人工处理连接问题。")
    if state.mode == "ap":
        return Action(kind="handoff", text="当前版本只支持路由模式，AP 模式请转人工处理。")
    if state.setup_complete is False:
        return Action(kind="handoff", text="当前版本只处理已完成初始设置后的问题，请转人工协助设置。")
    if state.others_affected is False:
        return Action(kind="handoff", text="当前版本只处理多台设备都无法上网的情况，单台设备问题请转人工处理。")

    # 3. 先接住上一次网线检查的反馈，不能先发出同一项检查。
    cable_result = state.check_results.get("check_wan_cable")
    if cable_result in ("failed", "unable"):
        text = "检查连接后仍无法上网" if cable_result == "failed" else "无法完成连接检查"
        return Action(kind="handoff", text=f"你反馈{text}，当前版本没有后续检查步骤，请转人工继续处理。")
    if cable_result is not None:
        return Action(kind="ask_user", text="完成连接检查后，现在可以上网了吗？")
    if state.pending_check == "check_wan_cable":
        return Action(kind="ask_user", text="请反馈连接检查的结果：已经恢复、仍无法上网，还是无法完成检查？")

    # 4. 没有检查需要等待时，才逐项补齐适用条件。每轮只问一项。
    if state.wifi_connected is None:
        return Action(kind="ask_user", text="当前设备是否已经连接到路由器的 Wi-Fi？")
    if state.others_affected is None:
        return Action(kind="ask_user", text="同一网络中的其他设备是否也无法上网？")
    if state.setup_complete is None:
        return Action(kind="ask_user", text="路由器是否已经完成初始设置？")
    if state.mode is None:
        return Action(kind="ask_user", text="路由器当前是路由模式，还是 AP 模式？")

    # 5. 条件齐了，先查看 WAN；发出过就等答案，不重复推荐。
    if state.wan_status is None:
        if state.pending_check == "internet_status":
            return Action(kind="ask_user", text="请反馈看到的 Internet IP：是 0.0.0.0、不是 0.0.0.0，还是无法判断？")
        evidence = evidence_by_id.get("internet_status_read")
        if not evidence or not evidence.get("summary") or not evidence.get("source_url"):
            return Action(kind="handoff", text="缺少查看 Internet 状态的资料，暂时无法继续引导，请转人工处理。")
        return Action(
            kind="recommend_check",
            text=evidence["summary"],
            check_id="internet_status",
            evidence_ids=["internet_status_read"],
        )

    # 6. 首版只继续处理 zero，其余情况明确转交。
    if state.wan_status == "unknown":
        return Action(kind="handoff", text="你无法判断 Internet IP 状态，请转人工协助查看。")
    if state.wan_status == "nonzero":
        return Action(kind="handoff", text="Internet IP 不是 0.0.0.0，当前版本没有覆盖这条排障路径，请转人工处理。")
    if state.wan_status == "zero":
        evidence = evidence_by_id.get("zero_ip_check_cable")
        if not evidence or not evidence.get("summary") or not evidence.get("source_url"):
            return Action(kind="handoff", text="缺少连接检查的资料，暂时无法继续推荐操作，请转人工处理。")
        return Action(
            kind="recommend_check",
            text=evidence["summary"],
            check_id="check_wan_cable",
            evidence_ids=["zero_ip_check_cable"],
        )
    return Action(kind="handoff", text="当前信息无法匹配已支持的排障路径，请转人工处理。")
