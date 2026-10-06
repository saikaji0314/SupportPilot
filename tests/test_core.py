import unittest
from dataclasses import asdict

from supportpilot.core import choose_next_action, merge_observation
from supportpilot.demo import evidence_by_id, observations
from supportpilot.state import SessionState


class CoreTests(unittest.TestCase):
    def ready_state(self, **changes):
        values = dict(wifi_connected=True, others_affected=True,
                      setup_complete=True, mode="router", wan_status="zero")
        values.update(changes)
        return SessionState(**values)

    def test_demo_reaches_handoff(self):
        state = SessionState()
        kinds = []
        for patch in observations:
            merge_observation(state, patch)
            action = choose_next_action(state, evidence_by_id)
            kinds.append(action.kind)
            if action.kind == "recommend_check":
                self.assertTrue(action.evidence_ids)
                state.pending_check = action.check_id
        self.assertEqual(kinds, ["ask_user", "recommend_check", "recommend_check", "handoff"])

    def test_waiting_does_not_repeat_check(self):
        for check_id, wan_status in [("internet_status", None), ("check_wan_cable", "zero")]:
            with self.subTest(check_id=check_id):
                state = self.ready_state(pending_check=check_id, wan_status=wan_status)
                self.assertEqual(choose_next_action(state, evidence_by_id).kind, "ask_user")

    def test_failure_kept_after_pending_is_cleared(self):
        for result in ("failed", "unable"):
            with self.subTest(result=result):
                state = self.ready_state(check_results={"check_wan_cable": result})
                self.assertEqual(choose_next_action(state, evidence_by_id).kind, "handoff")

    def test_reported_recovery_ends_troubleshooting(self):
        state = self.ready_state(restored=True, check_results={"check_wan_cable": "failed"})
        self.assertEqual(choose_next_action(state, evidence_by_id).kind, "resolved")

    def test_out_of_scope_does_not_request_more_fields(self):
        for field, value in [("wifi_connected", False), ("others_affected", False),
                             ("setup_complete", False), ("mode", "ap")]:
            with self.subTest(field=field):
                state = SessionState(**{field: value})
                self.assertEqual(choose_next_action(state, evidence_by_id).kind, "handoff")

    def test_other_wan_states_handoff(self):
        for status in ("unknown", "nonzero"):
            with self.subTest(status=status):
                self.assertEqual(choose_next_action(self.ready_state(wan_status=status), evidence_by_id).kind, "handoff")

    def test_missing_evidence_cannot_recommend(self):
        for status in (None, "zero"):
            with self.subTest(status=status):
                self.assertEqual(choose_next_action(self.ready_state(wan_status=status), {}).kind, "handoff")

    def test_decision_does_not_modify_state(self):
        state = self.ready_state(check_results={"check_wan_cable": "failed"}, pending_check="check_wan_cable")
        before = asdict(state)
        choose_next_action(state, evidence_by_id)
        self.assertEqual(asdict(state), before)

    def test_merge_keeps_history_and_accepts_false(self):
        state = SessionState(wifi_connected=True, check_results={"earlier": "failed"})
        merge_observation(state, {"wifi_connected": False, "mode": None,
                                  "check_results": {"check_wan_cable": "unable"}})
        self.assertIs(state.wifi_connected, False)
        self.assertEqual(state.check_results, {"earlier": "failed", "check_wan_cable": "unable"})


if __name__ == "__main__":
    unittest.main()
