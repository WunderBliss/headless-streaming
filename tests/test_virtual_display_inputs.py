from __future__ import annotations

import runpy
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "virtual-display"
NAMESPACE = runpy.run_path(str(SCRIPT), run_name="virtual_display_input_tests")
PARSE_DIMENSION = NAMESPACE["_parse_width_height"]
PARSE_FPS = NAMESPACE["_parse_fps"]
ERROR = NAMESPACE["VirtualDisplayError"]
ACTIVATE_CONFIG = NAMESPACE["_activate_config"]
SET_KSCREEN = NAMESPACE["_set_kscreen"]
KSCREEN_MODE = NAMESPACE["KscreenMode"]
CONFIG = NAMESPACE["CONFIG_SUPPORT"]


class StrictInputTests(unittest.TestCase):
    def test_valid_values(self) -> None:
        self.assertEqual(PARSE_DIMENSION("6016", "WIDTH", 16384), 6016)
        self.assertEqual(PARSE_FPS("59.94"), 59.94)

    def test_dimensions_reject_noncanonical_or_unbounded_values(self) -> None:
        for value in ("", "-1", "+1", "01", "1.0", "3840x2160", "9" * 5000):
            with self.subTest(value=value[:20]):
                with self.assertRaises(ERROR):
                    PARSE_DIMENSION(value, "WIDTH", 16384)

    def test_fps_rejects_expressions_and_nonfinite_forms(self) -> None:
        for value in ("", "-60", "+60", ".5", "1e2", "60/1", "nan", "inf", "1." + "0" * 100):
            with self.subTest(value=value[:20]):
                with self.assertRaises(ERROR):
                    PARSE_FPS(value)

    def test_kscreen_setters_are_scoped_to_configured_connector(self) -> None:
        configuration = CONFIG.RuntimeConfig(
            schema_version=1,
            desktop_user="alice",
            desktop_uid=1000,
            pci_slot="0000:c5:00.0",
            pci_vendor="1002",
            pci_device="1586",
            driver="amdgpu",
            connector="DP-3",
        )
        ACTIVATE_CONFIG(configuration)
        calls: list[list[str]] = []
        with mock.patch.dict(
            SET_KSCREEN.__globals__,
            {"_run_kscreen": lambda arguments: calls.append(arguments)},
        ):
            SET_KSCREEN(KSCREEN_MODE("mode_7", 2560, 1600, 120.0))
        self.assertEqual(
            calls,
            [
                [
                    "output.DP-3.enable",
                    "output.DP-3.mode.mode_7",
                    "output.DP-3.scale.1",
                ]
            ],
        )
        self.assertNotIn("DP-1", " ".join(calls[0]))


if __name__ == "__main__":
    unittest.main()
