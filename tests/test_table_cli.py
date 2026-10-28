import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ngspice_logcheck.table_cli import main


class TableCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.baseline = self.root / "baseline.csv"
        self.candidate = self.root / "candidate.csv"
        self.spec = self.root / "limits.json"
        self.header = "test,corner,point,measurement,value,unit,status\n"
        self.baseline.write_text(self.header + "ac,tt,nominal,gain,65,dB,ok\n", encoding="utf-8")
        self.candidate.write_text(self.header + "ac,tt,nominal,gain,58,dB,ok\n", encoding="utf-8")
        self.spec.write_text(json.dumps({"schemaVersion": 1, "measurements": [{"test": "ac", "corner": "tt", "point": "nominal", "measurement": "gain", "unit": "dB", "min": 60}]}), encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, extras=()):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(self.baseline), str(self.candidate), "--spec", str(self.spec), *extras])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_regression_artifacts_fingerprints_and_context(self):
        html_file = self.root / "review.html"
        json_file = self.root / "review.json"
        code, stdout, stderr = self.invoke(["--format", "json", "--html-out", str(html_file), "--json-out", str(json_file)])
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report, json.loads(json_file.read_text()))
        self.assertEqual(report["regressions"], 1)
        self.assertEqual(report["inputs"]["candidateCsvSha256"], hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        self.assertEqual(report["rows"][0]["unit"], "dB")
        self.assertIn("Candidate checks fail", html_file.read_text())
        self.assertNotIn(str(self.root), html_file.read_text())

    def test_matching_valid_tables_pass(self):
        self.candidate.write_bytes(self.baseline.read_bytes())
        self.assertEqual(self.invoke()[0], 0)

    def test_do_not_overwrite_or_alias_inputs(self):
        before = self.candidate.read_bytes()
        self.assertEqual(self.invoke(["--json-out", str(self.candidate)])[0], 2)
        self.assertEqual(self.candidate.read_bytes(), before)
        fresh = self.root / "fresh"
        self.assertEqual(self.invoke(["--json-out", str(fresh), "--html-out", str(fresh)])[0], 2)
        self.assertFalse(fresh.exists())

    def test_invalid_native_style_header_and_spec_do_not_write_artifacts(self):
        self.candidate.write_text("Output,Test,Nominal\ngain,ac,65\n")
        output = self.root / "invalid.html"
        self.assertEqual(self.invoke(["--html-out", str(output)])[0], 2)
        self.assertFalse(output.exists())
        self.candidate.write_bytes(self.baseline.read_bytes())
        self.spec.write_text('{"schemaVersion":1,"schemaVersion":1}')
        self.assertEqual(self.invoke()[0], 2)

    def test_unicode_decode_error_is_generic_and_empty(self):
        self.candidate.write_bytes(b"\xff")
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("UTF-8", stderr)

    def test_arbitrary_identity_labels_are_escaped_in_html(self):
        label = "<script>alert(1)</script>"
        for file, value in ((self.baseline, 65), (self.candidate, 58)):
            file.write_text(self.header + f"{label},tt,nominal,gain,{value},dB,ok\n")
        spec = json.loads(self.spec.read_text())
        spec["measurements"][0]["test"] = label
        self.spec.write_text(json.dumps(spec))
        output = self.root / "escaped.html"
        self.assertEqual(self.invoke(["--html-out", str(output)])[0], 1)
        rendered = output.read_text()
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script", rendered)
        self.assertIn("Content-Security-Policy", rendered)


if __name__ == "__main__":
    unittest.main()
