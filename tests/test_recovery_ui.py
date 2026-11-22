import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RecoveryUIArtifactTests(unittest.TestCase):
    def test_node_frontend_suite_passes_when_node_is_available(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is not installed; browser-side deterministic tests are unavailable.")
        completed = subprocess.run(
            ["node", "--test", os.path.join(ROOT, "tests", "js", "recovery_ui.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("pass 14", completed.stdout)

    def test_render_module_never_uses_unsafe_inner_html(self):
        view_path = os.path.join(ROOT, "web", "js", "recovery_view.js")
        with open(view_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("innerHTML", source)
        self.assertIn("createTextNode", source)

    def test_index_wires_modules_sse_and_polling_fallback(self):
        html_path = os.path.join(ROOT, "web", "index.html")
        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        for expected in (
            "/js/recovery_data.js",
            "/js/recovery_view.js",
            "RecoveryData.buildProjection",
            "RecoveryView.renderProjection",
            "pollAuditFallback",
            "sseFailed",
            "aria-live=\"polite\"",
        ):
            self.assertIn(expected, html)


if __name__ == "__main__":
    unittest.main()
