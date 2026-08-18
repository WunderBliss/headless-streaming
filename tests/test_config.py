from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "config.py"
SPEC = importlib.util.spec_from_file_location("virtual_display_config_tests", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CONFIG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONFIG
SPEC.loader.exec_module(CONFIG)


VALID = """\
schema_version=1
desktop_user=alice
desktop_uid=1000
pci_slot=0000:c5:00.0
pci_vendor=1002
pci_device=1586
driver=amdgpu
connector=DP-3
"""


class ConfigurationTests(unittest.TestCase):
    def test_valid_round_trip(self) -> None:
        parsed = CONFIG.parse_config_text(VALID)
        self.assertEqual(parsed.desktop_user, "alice")
        self.assertEqual(parsed.desktop_uid, 1000)
        self.assertEqual(parsed.connector, "DP-3")
        self.assertEqual(CONFIG.parse_config_text(parsed.text()), parsed)

    def test_unknown_duplicate_missing_and_unsafe_values_fail(self) -> None:
        invalid = (
            VALID + "command=/bin/sh\n",
            VALID.replace("schema_version=1\n", "schema_version=1\nschema_version=1\n"),
            VALID.replace("connector=DP-3\n", ""),
            VALID.replace("connector=DP-3", "connector=DP-3/../../HDMI-A-1"),
            VALID.replace("pci_slot=0000:c5:00.0", "pci_slot=../../sys"),
            VALID.replace("desktop_uid=1000", "desktop_uid=0"),
        )
        for text in invalid:
            with self.subTest(text=text[-60:]):
                with self.assertRaises(CONFIG.ConfigError):
                    CONFIG.parse_config_text(text)

    def test_secure_loader_rejects_writable_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topology.conf"
            path.write_text(VALID)
            path.chmod(0o666)
            with self.assertRaises(CONFIG.ConfigError):
                CONFIG.load_config(path)
            self.assertEqual(
                CONFIG.load_config(path, require_secure_ownership=False).connector,
                "DP-3",
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_loader_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text(VALID)
            link = Path(directory) / "link"
            link.symlink_to(target)
            with self.assertRaises(CONFIG.ConfigError):
                CONFIG.load_config(link, require_secure_ownership=False)


if __name__ == "__main__":
    unittest.main()
