"""Regression tests for supplied-report validation and descriptive comparison."""

import copy
import json
import math
import unittest

from ngspice_logcheck.compare import compare_reports
from ngspice_logcheck.core import check_log


def report(text="x=1", limits=None):
    result = check_log(text, {"schemaVersion": 1, "measurements": limits or {"x": {"min": 0, "max": 2}}})
    result["inputs"] = {"logSha256": "a" * 64, "specSha256": "b" * 64}
    result["tool"] = {"name": "ngspice-logcheck", "version": "0.1.0"}
    return result


class ComparisonTests(unittest.TestCase):
    def test_descriptive_delta_regression_and_improvement(self):
        baseline = report("x=1\ny=5", {"x": {"min": 0, "max": 2}, "y": {"max": 3}})
        candidate = report("y=2\nx=3", {"y": {"max": 3}, "x": {"max": 2, "min": 0}})
        original = copy.deepcopy(baseline)
        comparison = compare_reports(baseline, candidate)
        self.assertFalse(comparison["passed"])
        self.assertFalse(comparison["baselinePassed"])
        self.assertEqual(comparison["regressions"], 1)
        self.assertEqual(comparison["improvements"], 1)
        self.assertEqual(comparison["checks"][0]["delta"], 2)
        self.assertEqual(comparison["checks"][0]["relativeDelta"], 2)
        self.assertEqual(comparison["checks"][1]["delta"], -3)
        self.assertTrue(comparison["checks"][0]["regressed"])
        self.assertTrue(comparison["checks"][1]["improved"])
        self.assertEqual(baseline, original)

    def test_case_insensitive_names_and_semantically_equivalent_limits(self):
        baseline = report()
        candidate = report("X=1.5", {"X": {"max": 2.0, "min": 0.0}})
        candidate["inputs"]["specSha256"] = "C" * 64
        comparison = compare_reports(baseline, candidate)
        self.assertEqual(comparison["checks"][0]["name"], "x")
        self.assertEqual(comparison["checks"][0]["delta"], 0.5)
        self.assertEqual(comparison["inputs"]["candidate"]["specSha256"], "c" * 64)

    def test_unchanged_passes_can_have_numeric_delta_without_regression(self):
        comparison = compare_reports(report("x=1"), report("x=1.9"))
        self.assertTrue(comparison["passed"])
        self.assertEqual(comparison["regressions"], 0)
        self.assertEqual(comparison["improvements"], 0)

    def test_zero_baseline_relative_delta_is_null(self):
        check = compare_reports(report("x=0"), report("x=1"))["checks"][0]
        self.assertEqual(check["delta"], 1)
        self.assertIsNone(check["relativeDelta"])
        self.assertIn("relative-delta-undefined-zero-baseline", check["notes"])

    def test_missing_duplicate_and_failed_measurement_evidence_stays_failed(self):
        for text, reason in [("unrelated=1", "missing-measurement"), ("x=1\nx=1", "ambiguous-duplicates"), ("x=bad", "invalid-value"), ("x=1\nmeasure 'x' failed", "measurement-failed")]:
            with self.subTest(reason=reason):
                candidate = report(text)
                candidate["passed"] = True
                candidate["checks"][0]["status"] = "passed"
                comparison = compare_reports(report(), candidate)
                self.assertFalse(comparison["passed"])
                self.assertEqual(comparison["checks"][0]["candidateReason"], reason)
                self.assertEqual(comparison["regressions"], 1)

    def test_forged_passed_flags_and_numeric_reasons_are_recomputed(self):
        candidate = report("x=3")
        candidate["passed"] = True
        candidate["checks"][0]["status"] = "passed"
        candidate["checks"][0]["reason"] = "within-limits"
        comparison = compare_reports(report(), candidate)
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["checks"][0]["candidateReason"], "above-maximum")
        candidate = report("x=1")
        candidate["passed"] = False
        candidate["checks"][0]["status"] = "failed"
        candidate["checks"][0]["reason"] = "above-maximum"
        self.assertTrue(compare_reports(report(), candidate)["passed"])

    def test_global_errors_force_overall_fail_without_inventing_metric_regression(self):
        comparison = compare_reports(report("x=1\nWarning: convergence recovery"), report("x=1\nError: failure"))
        self.assertTrue(comparison["baselinePassed"])
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["regressions"], 0)
        self.assertEqual(comparison["checks"][0]["candidateStatus"], "passed")
        self.assertEqual(comparison["candidateDiagnostics"][0]["severity"], "error")
        resolved = compare_reports(report("x=1\nError: baseline failure"), report("x=1"))
        self.assertFalse(resolved["baselinePassed"])
        self.assertTrue(resolved["passed"])
        self.assertEqual(resolved["improvements"], 0)

    def test_spec_changes_are_incomparable(self):
        for candidate in [report("y=1", {"y": {"min": 0, "max": 2}}), report("x=1", {"x": {"min": 0}}), report("x=1", {"x": {"min": 0, "max": 3}})]:
            with self.assertRaisesRegex(ValueError, "incomparable"):
                compare_reports(report(), candidate)

    def test_subtraction_and_ratio_overflow_never_emit_infinite_json(self):
        limits = {"x": {"min": -1.7e308, "max": 1.7e308}}
        overflow = compare_reports(report("x=-1e308", limits), report("x=1e308", limits))
        self.assertIsNone(overflow["checks"][0]["delta"])
        self.assertIsNone(overflow["checks"][0]["relativeDelta"])
        self.assertIn("delta-overflow", overflow["checks"][0]["notes"])
        ratio = compare_reports(report("x=1e-308", limits), report("x=1e308", limits))
        self.assertEqual(ratio["checks"][0]["delta"], 1e308)
        self.assertIsNone(ratio["checks"][0]["relativeDelta"])
        self.assertIn("relative-delta-overflow", ratio["checks"][0]["notes"])
        json.dumps(overflow, allow_nan=False)
        json.dumps(ratio, allow_nan=False)

    def test_report_schema_and_required_fields_are_strict(self):
        for changes in [{"schemaVersion": True}, {"schemaVersion": 1.0}, {"schemaVersion": 2}, {"passed": 1}, {"checks": []}, {"diagnostics": None}, {"inputs": {}}, {"limitations": "raw"}, {"rawLog": "PRIVATE"}, {"tool": {"name": "other", "version": "1"}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare_reports(report(), {**report(), **changes})
        for key in report():
            if key != "tool":
                candidate = report()
                del candidate[key]
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    compare_reports(report(), candidate)

    def test_measurement_entries_and_duplicate_names_are_strict(self):
        for changes in [{"value": True}, {"value": math.inf}, {"value": math.nan}, {"value": 10**10000}, {"value": "1"}, {"name": "bad-name"}, {"status": "unknown"}, {"limits": {"min": False}}, {"limits": {"max": -1, "min": 0}}, {"reason": "raw log text"}, {"lineNumbers": [True]}, {"lineNumbers": [0]}, {"lineNumbers": [2, 1]}, {"lineNumbers": [1, 1]}, {"lineNumbers": []}, {"rawLog": "PRIVATE"}]:
            candidate = report()
            candidate["checks"][0].update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                compare_reports(report(), candidate)
        candidate = report()
        duplicate = copy.deepcopy(candidate["checks"][0])
        duplicate["name"] = "X"
        candidate["checks"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "unique"):
            compare_reports(report(), candidate)

    def test_diagnostics_cannot_downgrade_error_or_copy_arbitrary_text(self):
        for diagnostic in [{"line": True, "severity": "error", "code": "ngspice-error"}, {"line": -1, "severity": "error", "code": "ngspice-error"}, {"line": 1, "severity": "warning", "code": "ngspice-error"}, {"line": 1, "severity": "error", "code": "RAW PRIVATE LOG"}, {"line": 1, "severity": "error", "code": "ngspice-error", "message": "PRIVATE"}]:
            candidate = report()
            candidate["diagnostics"] = [diagnostic]
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                compare_reports(report(), candidate)
        candidate = report()
        candidate["limitations"] = ["PRIVATE SOURCE EXCERPT"]
        self.assertNotIn("PRIVATE SOURCE EXCERPT", json.dumps(compare_reports(report(), candidate)))

    def test_hashes_are_required_and_validated_without_freshness_claim(self):
        for inputs in [{"logSha256": "a" * 63, "specSha256": "b" * 64}, {"logSha256": "g" * 64, "specSha256": "b" * 64}, {"logSha256": True, "specSha256": "b" * 64}, {"logSha256": "a" * 64, "specSha256": "b" * 64, "path": "PRIVATE"}]:
            candidate = report()
            candidate["inputs"] = inputs
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                compare_reports(report(), candidate)
        same_identifiers = compare_reports(report("x=1"), report("x=2"))
        self.assertTrue(same_identifiers["passed"])
        self.assertIn("user-controlled", " ".join(same_identifiers["limitations"]))


if __name__ == "__main__":
    unittest.main()
