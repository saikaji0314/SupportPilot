# 资料驱动回复实验输入

这些合成案例用于验证同一个模型函数能完成售后问答、提出检查和识别资料不足。它们是显式给定资料的实验，不是已经完成的 RAG。

- `passages.json`：根据 [TP-Link 美国站 FAQ 1556](https://www.tp-link.com/us/support/faq/1556/) 编写的简短中文摘要，保留来源和章节；不包含完整原文。
- `cases.json`：用户问题、会话记录及本轮可读片段。案例的预期答案不传给模型。
- `product_ids` 是实验中的资料归属；该 FAQ 不是特定硬件或固件版本的专属说明。当前产品档案为预设，未自动识别设备。

资料没有人工配置的操作 ID、前提表达式或后继节点。章节条件保留在正文中，由模型阅读。会话里的 `check-1` 是某次已发出的检查记录编号，与资料无关。

预览输入：

```powershell
python -m supportpilot.grounded_demo --case case-01
```

命令只显示输入。`supportpilot.grounded.propose_response` 是待实现接口；完成后可向 `run_case(model, "case-01")` 传入已配置的模型客户端。未通过真实模型评测前，不宣称实验已经成功。
