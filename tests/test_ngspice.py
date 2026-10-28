"""Optional live simulator tests. CI makes this job mandatory on Linux."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ngspice_logcheck.core import check_log, load_spec

ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = os.environ.get("NGSPICE") or shutil.which("ngspice")


@unittest.skipUnless(SIMULATOR, "Set NGSPICE or install ngspice for live simulator tests")
class LiveNgspiceTests(unittest.TestCase):
    def simulate(self, deck):
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([SIMULATOR, "-n", "-b", str(ROOT / "examples" / deck)], cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", timeout=20)

    def test_real_rc_values_and_metadata_pass(self):
        result = self.simulate("rc.cir")
        self.assertEqual(result.returncode, 0, result.stdout)
        report = check_log(result.stdout, load_spec((ROOT / "examples/limits.json").read_text()))
        self.assertTrue(report["passed"], report)
        self.assertEqual(len(report["checks"]), 2)
        self.assertAlmostEqual(report["checks"][0]["value"], 1.0, places=3)

    def test_unreachable_measurement_fails_even_when_simulator_exits_zero(self):
        result = self.simulate("failed-measure.cir")
        # ngspice 47 reproduces exit 0; other versions may fix their exit status.
        self.assertIn(result.returncode, (0, 1), result.stdout)
        report = check_log(result.stdout, load_spec((ROOT / "examples/limits.json").read_text()))
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][1]["reason"], "measurement-failed")

    def test_actual_simulated_value_outside_declared_limit_fails(self):
        result = self.simulate("rc.cir")
        spec = load_spec('{"schemaVersion":1,"measurements":{"vout_final":{"max":0.5}}}')
        report = check_log(result.stdout, spec)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][0]["reason"], "above-maximum")
