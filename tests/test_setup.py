from __future__ import annotations

import contextlib
import io
import runpy
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "headless-virtual-display-setup"
NAMESPACE = runpy.run_path(str(SCRIPT), run_name="virtual_display_setup_tests")
CONFIG = NAMESPACE["CONFIG"]


class SetupTests(unittest.TestCase):
    def test_sudoers_authorizes_only_fixed_helper_operations(self) -> None:
        text = NAMESPACE["_sudoers_text"]("alice")
        for operation in ("apply", "retune", "remove", "probe"):
            self.assertIn(f"headless-virtual-display-root {operation}", text)
        self.assertIn("alice ALL=(root) NOPASSWD: NOEXEC:", text)
        self.assertNotIn("/bin/sh", text)
        self.assertNotIn("virtual-display sunshine-up", text)

    def test_next_steps_include_unattended_boot_security_warning(self) -> None:
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
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            NAMESPACE["_print_next_steps"](configuration, None)
        rendered = output.getvalue()
        self.assertIn("autologin", rendered)
        self.assertIn("KWallet password", rendered)
        self.assertIn("reduce security", rendered)
        self.assertIn("physical-access and credential risks", rendered)


if __name__ == "__main__":
    unittest.main()
