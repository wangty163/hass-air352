from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "air352"),
)

from state import PropertyState  # noqa: E402


class PropertyStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = PropertyState()
        self.state.data = {
            "iot-1": {
                "PowerSwitch": {"value": 1, "time": 1_000},
                "PM25": {"value": 12, "time": 1_000},
            }
        }

    def test_stale_poll_cannot_undo_optimistic_command(self) -> None:
        self.state.begin_command(
            "iot-1",
            {"PowerSwitch": 0},
            now_ms=2_000,
            monotonic_now=10,
        )

        changed = self.state.merge_device(
            "iot-1",
            {"PowerSwitch": {"value": 1, "time": 1_000}},
            source="rest",
            monotonic_now=11,
        )

        self.assertFalse(changed)
        self.assertEqual(
            self.state.data["iot-1"]["PowerSwitch"],
            {"value": 0, "time": 2_000},
        )

    def test_matching_push_confirms_command_and_blocks_older_state(self) -> None:
        self.state.begin_command(
            "iot-1",
            {"PowerSwitch": 0},
            now_ms=2_000,
            monotonic_now=10,
        )

        self.assertTrue(
            self.state.merge_device(
                "iot-1",
                {"PowerSwitch": {"value": 0, "time": 2_500}},
                source="push",
                monotonic_now=11,
            )
        )
        self.assertFalse(
            self.state.merge_device(
                "iot-1",
                {"PowerSwitch": {"value": 1, "time": 1_500}},
                source="rest",
                monotonic_now=12,
            )
        )
        self.assertEqual(
            self.state.data["iot-1"]["PowerSwitch"]["value"],
            0,
        )

    def test_expired_command_accepts_actual_device_state(self) -> None:
        self.state.begin_command(
            "iot-1",
            {"PowerSwitch": 0},
            now_ms=2_000,
            monotonic_now=10,
        )

        self.assertTrue(
            self.state.merge_device(
                "iot-1",
                {"PowerSwitch": {"value": 1, "time": 1_000}},
                source="rest",
                monotonic_now=26,
            )
        )
        self.assertEqual(
            self.state.data["iot-1"]["PowerSwitch"]["value"],
            1,
        )

    def test_failed_command_rolls_back_only_its_pending_values(self) -> None:
        token = self.state.begin_command(
            "iot-1",
            {"PowerSwitch": 0, "NewProperty": 1},
            now_ms=2_000,
            monotonic_now=10,
        )

        self.state.rollback_command(token)

        self.assertEqual(
            self.state.data["iot-1"]["PowerSwitch"],
            {"value": 1, "time": 1_000},
        )
        self.assertNotIn("NewProperty", self.state.data["iot-1"])

    def test_push_merges_all_sensor_values_by_timestamp(self) -> None:
        changed = self.state.merge_device(
            "iot-1",
            {
                "PM25": {"value": 9, "time": 2_000},
                "TVOC": {"value": 220, "time": 2_000},
            },
            source="push",
            monotonic_now=10,
        )

        self.assertTrue(changed)
        self.assertEqual(self.state.data["iot-1"]["PM25"]["value"], 9)
        self.assertEqual(self.state.data["iot-1"]["TVOC"]["value"], 220)


if __name__ == "__main__":
    unittest.main()
