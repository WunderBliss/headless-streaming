from __future__ import annotations

import runpy
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "virtual-display"
NAMESPACE = runpy.run_path(str(SCRIPT), run_name="virtual_display_input_tests")
PARSE_DIMENSION = NAMESPACE["_parse_width_height"]
PARSE_FPS = NAMESPACE["_parse_fps"]
ERROR = NAMESPACE["VirtualDisplayError"]


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


if __name__ == "__main__":
    unittest.main()
