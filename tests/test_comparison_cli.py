import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ngspice_logcheck.cli import main
from ngspice_logcheck.core import check_log, load_spec


class ComparisonCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.spec = load_spec('{"schemaVersion":1,"measurements":{"rise_time":{"max":3}}}')
        self.baseline = self.root / "baseline.json"
        self.candidate = self.root / "candidate.json"
        for path, value in ((self.baseline, 2), (self.candidate, 4)):
            report = check_log(f"rise_time={value}\n", self.spec)
            report["inputs"] = {"logSha256": hashlib.sha256(str(value).encode()).hexdigest(), "specSha256": "a" * 64}
            path.write_text(json.dumps(report), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, extras=()):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["compare", str(self.baseline), str(self.candidate), *extras])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_regression_outputs_self_contained_review_packet(self):
        output = self.root / "review.html"
        code, stdout, stderr = self.invoke(["--html-out", str(output), "--format", "json"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["regressions"], 1)
        text = output.read_text(encoding="utf-8")
        self.assertIn("Supplied candidate checks fail", text)
        self.assertIn("rise_time", text)
        self.assertIn("Content-Security-Policy", text)
        self.assertNotIn("<script", text.lower())
        self.assertNotIn(str(self.root), text)

    def test_alias_and_existing_output_and_bad_json_fail_without_overwrite(self):
        before = self.baseline.read_bytes()
        self.assertEqual(self.invoke(["--html-out", str(self.baseline)])[0], 2)
        self.assertEqual(self.baseline.read_bytes(), before)
        self.candidate.write_text('{"schemaVersion":1,"schemaVersion":1}')
        self.assertEqual(self.invoke()[0], 2)

    def test_changed_limits_do_not_produce_a_comparison(self):
        report = json.loads(self.candidate.read_text())
        report["checks"][0]["limits"]["max"] = 5
        self.candidate.write_text(json.dumps(report))
        output = self.root / "misleading.html"
        code, stdout, stderr = self.invoke(["--html-out", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertFalse(output.exists())

    def test_report_json_nonzero_underflow_is_rejected(self):
        report = self.candidate.read_text().replace('"value": 4.0', '"value": 1e-9999')
        self.candidate.write_text(report)
        self.assertEqual(self.invoke()[0], 2)

    def test_review_packet_preserves_values_near_a_limit(self):
        from ngspice_logcheck.comparison_cli import display_number
        self.assertNotEqual(display_number(1.000000001), display_number(1.0))


if __name__ == "__main__":
    unittest.main()
