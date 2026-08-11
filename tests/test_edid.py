from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "edid.py"
SPEC = importlib.util.spec_from_file_location("virtual_display_edid_tests", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EDID = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EDID
SPEC.loader.exec_module(EDID)


class NormalizationTests(unittest.TestCase):
    def assert_valid(self, normalized) -> None:
        EDID.validate_edid(
            normalized.edid,
            normalized.width,
            normalized.height,
            normalized.refresh_hz,
            require_poc_identity=True,
        )

    def test_known_exact_modes_remain_exact(self) -> None:
        for request in (
            (2560, 1600, 120.0),
            (1920, 1080, 144.0),
            (1280, 800, 90.0),
        ):
            with self.subTest(request=request):
                normalized = EDID.normalize_mode(*request)
                self.assertFalse(normalized.fallback)
                self.assertEqual(
                    (normalized.width, normalized.height, normalized.refresh_hz),
                    request,
                )
                self.assert_valid(normalized)

    def test_4k_90_falls_back_only_in_refresh(self) -> None:
        normalized = EDID.normalize_mode(3840, 2160, 90.0)
        self.assertTrue(normalized.fallback)
        self.assertFalse(normalized.emergency)
        self.assertEqual(
            (normalized.width, normalized.height, normalized.refresh_hz),
            (3840, 2160, 60.0),
        )
        self.assertEqual(normalized.aspect_error, 0.0)
        self.assert_valid(normalized)

    def test_5k_and_6016_fit_to_4k_without_aspect_change(self) -> None:
        for request in ((5120, 2880, 60.0), (6016, 3384, 60.0)):
            with self.subTest(request=request):
                normalized = EDID.normalize_mode(*request)
                self.assertTrue(normalized.fallback)
                self.assertEqual(
                    (normalized.width, normalized.height, normalized.refresh_hz),
                    (3840, 2160, 60.0),
                )
                self.assertEqual(normalized.aspect_error, 0.0)
                self.assert_valid(normalized)

    def test_width_rounding_never_exceeds_request(self) -> None:
        normalized = EDID.normalize_mode(2559, 1600, 60.0)
        self.assertTrue(normalized.fallback)
        self.assertLessEqual(normalized.width, 2559)
        self.assertLessEqual(normalized.height, 1600)
        self.assertEqual(normalized.width % 8, 0)
        self.assertLessEqual(
            normalized.aspect_error, EDID.MAX_FALLBACK_ASPECT_ERROR
        )
        self.assert_valid(normalized)

    def test_request_bounds_are_enforced_before_generation(self) -> None:
        for request in (
            (0, 1080, 60.0),
            (1920, 0, 60.0),
            (EDID.MAX_REQUEST_WIDTH + 1, 1080, 60.0),
            (1920, EDID.MAX_REQUEST_HEIGHT + 1, 60.0),
            (1920, 1080, 0.0),
            (1920, 1080, EDID.MAX_REQUEST_HZ + 1),
        ):
            with self.subTest(request=request):
                with self.assertRaises(EDID.EdidError):
                    EDID.normalize_mode(*request)

    def test_emergency_aspect_change_is_marked(self) -> None:
        normalized = EDID.normalize_mode(200, 100, 60.0)
        self.assertTrue(normalized.fallback)
        self.assertTrue(normalized.emergency)
        self.assertGreater(normalized.aspect_error, 0.0)
        self.assertEqual(
            (normalized.width, normalized.height, normalized.refresh_hz),
            EDID.BASELINE_MODE,
        )
        self.assert_valid(normalized)


if __name__ == "__main__":
    unittest.main()
