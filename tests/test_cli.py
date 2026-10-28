import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from ngspice_logcheck.cli import main, read_bounded, xml_safe


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.log = self.root / "input.log"
        self.spec = self.root / "limits.json"
        self.log.write_text("gain = 2.5\n", encoding="utf-8")
        self.spec.write_text('{"schemaVersion":1,"measurements":{"gain":{"min":2,"max":3}}}', encoding="utf-8")
        self.args = [str(self.log), "--spec", str(self.spec)]

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, extra=()):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(self.args + list(extra))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_json_and_junit_artifacts_have_consistent_failures_and_hashes(self):
        self.log.write_text("gain = 4\nError: bad simulation\n", encoding="utf-8")
        report, junit = self.root / "report.json", self.root / "junit.xml"
        code, output, errors = self.invoke(["--format", "json", "--json-out", str(report), "--junit-out", str(junit)])
        self.assertEqual(code, 1)
        self.assertEqual(errors, "")
        data = json.loads(output)
        self.assertEqual(data, json.loads(report.read_text()))
        self.assertFalse(data["passed"])
        self.assertEqual(data["inputs"]["logSha256"], hashlib.sha256(self.log.read_bytes()).hexdigest())
        suite = ET.parse(junit).getroot()
        self.assertEqual(suite.attrib["tests"], "2")
        self.assertEqual(suite.attrib["failures"], "2")
        self.assertNotIn("bad simulation", junit.read_text())
        self.assertNotIn(str(self.root), output)

    def test_success(self):
        code, output, errors = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn("PASS", output)
        self.assertEqual(errors, "")

    def test_do_not_overwrite_files_or_alias_inputs(self):
        for filename in (self.log, self.spec, self.root / "existing.json"):
            if not filename.exists():
                filename.write_text("unchanged")
            before = filename.read_bytes()
            self.assertEqual(self.invoke(["--json-out", str(filename)])[0], 2)
            self.assertEqual(filename.read_bytes(), before)
        fresh = self.root / "fresh"
        self.assertEqual(self.invoke(["--json-out", str(fresh), "--junit-out", str(fresh)])[0], 2)
        self.assertFalse(fresh.exists())

    def test_malformed_utf8_and_invalid_config_exit_two_without_data(self):
        self.log.write_bytes(b"\xff")
        code, output, errors = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("UTF-8", errors)
        self.log.write_text("gain = 2.5\n")
        self.spec.write_text('{"schemaVersion":1,"measurements":{"gain":{"max":true}}}')
        self.assertEqual(self.invoke()[0], 2)

    def test_bounded_reads_and_regular_file_requirement(self):
        with self.assertRaises(ValueError):
            read_bounded(self.log, 2)
        if hasattr(os, "mkfifo"):
            fifo = self.root / "pipe"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                read_bounded(fifo, 1024)

    def test_empty_input_does_not_pass_or_write_success_junit(self):
        self.log.write_text("")
        junit = self.root / "empty.xml"
        self.assertEqual(self.invoke(["--junit-out", str(junit)])[0], 1)
        self.assertGreater(int(ET.parse(junit).getroot().attrib["failures"]), 0)

    def test_xml_control_character_filter(self):
        self.assertEqual(xml_safe("a\x00\x01<&\n"), "a??<&\n")

    def test_module_entrypoint(self):
        result = subprocess.run([sys.executable, "-m", "ngspice_logcheck", *self.args, "--format", "json"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])


if __name__ == "__main__":
    unittest.main()
