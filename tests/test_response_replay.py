"""回放必须使用当轮输入，并且只请求回复环节。"""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from supportpilot.agent.grounded import GroundedResponse
from supportpilot.cli.response_replay import load_payload, replay


class ReplayTests(unittest.TestCase):
    def test_uses_updated_state_and_does_not_feed_original_reply(self):
        record = {"user_text": "设置了仍未恢复", "updated": {"product_id": "p", "status": "ongoing", "checks": []},
                  "after": {"facts": ["之后才得知的事实"]}, "passages": [],
                  "response": {"kind": "recommend_check", "text": "待审阅旧建议"}}
        with patch.object(Path, "read_text", return_value=json.dumps(record)), \
             patch.object(Path, "write_text") as write:
            payload, original = load_payload(Path("synthetic-turn.json"))
            reply = GroundedResponse(kind="ask_user", text="请确认缺少的当前参数。")
            with patch("supportpilot.cli.response_replay.propose_response", return_value=reply) as propose:
                result = replay("fake-model", payload)
                propose.assert_called_once_with("fake-model", user_text=record["user_text"],
                                                 state=record["updated"], passages=[])
            self.assertEqual(original, record["response"])
            self.assertEqual(result["errors"], [])
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
