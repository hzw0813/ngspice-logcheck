"""Meaningful parser/spec regression tests; no simulator or network needed."""

import copy
import json
import math
import unittest

from ngspice_logcheck.core import MAX_LOG_BYTES, check_log, load_spec


def spec(**measurements):
    return {"schemaVersion": 1, "measurements": measurements}


class SpecTests(unittest.TestCase):
    def test_valid_spec_returns_normalized_independent_limits(self):
        loaded = load_spec('{"schemaVersion":1,"measurements":{"rise_time":{"min":0,"max":2e-9},"gain":{"min":3}}}')
        self.assertEqual(loaded["measurements"]["rise_time"], {"min": 0.0, "max": 2e-9})
        self.assertIs(type(loaded["measurements"]["gain"]["min"]), float)

    def test_duplicate_json_keys_rejected_at_every_depth(self):
        for text in [
            '{"schemaVersion":1,"schemaVersion":1,"measurements":{"x":{"min":0}}}',
            '{"schemaVersion":1,"measurements":{"x":{"min":0},"x":{"max":2}}}',
            '{"schemaVersion":1,"measurements":{"x":{"min":0,"min":1}}}',
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_spec(text)

    def test_invalid_structure_versions_names_and_limits(self):
        invalid = [None, [], {}, {"schemaVersion": 1}, spec(), spec(x={}), spec(x={"target": 1}), spec(x={"min": True}), spec(x={"min": "1"}), spec(x={"min": None}), spec(x={"min": 2, "max": 1}), spec(x={"min": math.inf}), spec(x={"min": math.nan}), spec(x={"max": 10**10000}), spec(x={"min": 0}, X={"max": 1}), spec(**{"1bad": {"min": 0}}), spec(**{"µ": {"min": 0}}), spec(**{"a-b": {"min": 0}}), {**spec(x={"min": 0}), "extra": False}]
        invalid.extend({**spec(x={"min": 0}), "schemaVersion": version} for version in [True, False, 1.0, "1", 2])
        invalid.append(spec(**{f"x{i}": {"min": 0} for i in range(1001)}))
        for index, value in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                check_log("x = 1", value)

    def test_non_json_nonfinite_constants_and_exponents_rejected(self):
        for text in ["", "{broken", '{"schemaVersion":1,"measurements":{"x":{"min":NaN}}}', '{"schemaVersion":1,"measurements":{"x":{"min":Infinity}}}', '{"schemaVersion":1,"measurements":{"x":{"min":1e9999}}}', '{"schemaVersion":1,"measurements":{"x":{"min":1e-9999}}}', '{"schemaVersion":1,"measurements":{"x":{"min":0},"X":{"max":1}}}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_spec(text)

    def test_malformed_text_and_recursion_have_valueerror_boundary(self):
        for text in [None, b"{}", "\ud800", "[" * 2000 + "]" * 2000, " " * (1024 * 1024 + 1)]:
            with self.subTest(kind=type(text)), self.assertRaises(ValueError):
                load_spec(text)


class LogTests(unittest.TestCase):
    def test_realistic_scalar_forms_case_metadata_and_inclusive_bounds(self):
        limits = spec(delay={"min": 1e-9, "max": 1e-9}, gain={"min": 2}, peak={"max": 4}, when={"min": 0})
        original = copy.deepcopy(limits)
        text = "Measurements for Transient Analysis\n DELAY= 1.000e-09 targ= 2e-9 trig= 1e-9\n gain = +2. from = 0 to = 1e-3\npeak = .4E+1 at= 2.5e-4\nwhen = 0 with = 1.2\n"
        report = check_log(text, limits)
        self.assertTrue(report["passed"])
        self.assertEqual([item["lineNumbers"] for item in report["checks"]], [[2], [3], [4], [5]])
        self.assertEqual(limits, original)
        json.dumps(report, allow_nan=False)

    def test_negative_and_one_sided_values(self):
        report = check_log("x = -1.25\ny=+2E3", spec(x={"min": -2, "max": -1}, y={"max": 2000}))
        self.assertTrue(report["passed"])
        for value, bounds, reason in [("0.9", {"min": 1}, "below-minimum"), ("2.1", {"max": 2}, "above-maximum")]:
            result = check_log(f"x={value}", spec(x=bounds))
            self.assertFalse(result["passed"])
            self.assertEqual(result["checks"][0]["reason"], reason)

    def test_binary64_underflow_rejected_in_log_and_json_limits(self):
        for token in ["1e-9999", "-1e-9999", "1e-999999999999999999999999999999", "0e-999999999999999999999999999999"]:
            with self.subTest(token=token):
                report = check_log(f"x={token}", spec(x={"max": 0}))
                self.assertFalse(report["passed"])
                self.assertEqual(report["checks"][0]["reason"], "invalid-value")
                self.assertFalse(check_log(f"x=1 at={token}", spec(x={"min": 0}))["passed"])
                with self.assertRaises(ValueError):
                    load_spec('{"schemaVersion":1,"measurements":{"x":{"min":' + token + '}}}')
        self.assertTrue(check_log("x=0e-99", spec(x={"min": 0, "max": 0}))["passed"])

    def test_rejects_partial_nonfinite_suffix_and_arbitrary_tail_values(self):
        for value in ["NaN", "nan", "Inf", "-Infinity", "1e9999", "1e-9999", "1e", "1e3junk", "1 e-3", "1m", "1u", "1V", "1,2", "0x10", "1_000", "1 # comment", "1 at=nan", "1 at=1e9999", "1 at=1e-9999", "1from=0", "1 blah=2", "1 at=2 junk", "1 at=2 at=3", "1 from=1e3bad", "failed", "", "١"]:
            with self.subTest(value=value):
                report = check_log(f"x = {value}", spec(x={"min": -1e9, "max": 1e9}))
                self.assertFalse(report["passed"])
                self.assertIsNone(report["checks"][0]["value"])
                self.assertEqual(report["checks"][0]["reason"], "invalid-value")
                json.dumps(report, allow_nan=False)

    def test_duplicates_identical_conflicting_or_malformed_fail(self):
        for text in ["x=1\nx=1", "x=1\nX=2", "x=bad\nx=1"]:
            report = check_log(text, spec(x={"min": 0}))
            self.assertFalse(report["passed"])
            self.assertEqual(report["checks"][0]["reason"], "ambiguous-duplicates")
            self.assertEqual(report["checks"][0]["lineNumbers"], [1, 2])
            self.assertIsNone(report["checks"][0]["value"])

    def test_missing_assignments_require_anchored_exact_names(self):
        for text in ["", " \t\n", "prefix x=1", "other_x=1", ".meas tran x param=1", "x: 1", "x == 1"]:
            report = check_log(text, spec(x={"min": 0}))
            self.assertFalse(report["passed"])
            self.assertIsNone(report["checks"][0]["value"])
        self.assertEqual(check_log("unrelated arbitrary text", spec(x={"min": 0}))["checks"][0]["reason"], "missing-measurement")
        self.assertEqual(check_log("", spec(x={"min": 0}))["diagnostics"], [{"line": 0, "severity": "error", "code": "empty-log"}])

    def test_named_measurement_failure_overrides_valid_number(self):
        for failure in ["measure 'X' failed", 'measure "x" failed', "Error: measure x failed", ".meas tran x find v(out) at=1e-3 failed!", " meas ac x max v(out) failed!", ".measure dc x param='1' failed!"]:
            with self.subTest(failure=failure):
                report = check_log(f"x = 1\n{failure}", spec(x={"min": 0}))
                self.assertFalse(report["passed"])
                self.assertEqual(report["checks"][0]["reason"], "measurement-failed")
                self.assertEqual(report["checks"][0]["lineNumbers"], [1, 2])
                self.assertEqual(report["diagnostics"][0]["code"], "measurement-failed")

    def test_general_errors_anywhere_fail_even_after_passed_values(self):
        for line in ["Error: unavailable model", "Error on line 42: bad model", "Error(parse.c--checkvalid): zero length vector", " Fatal error: solver stopped", "Fatal: failure", "***ERROR*** model failed", "**** Error ****", "***FATAL ERROR***", "simulation aborted", "run simulation(s) aborted", "Simulation interrupted", "doAnalyses: TRAN: Timestep too small", "measure 'other' failed", ".meas tran other find v(out) failed!"]:
            with self.subTest(line=line):
                report = check_log(f"x = 1\n{line}", spec(x={"min": 0}))
                self.assertFalse(report["passed"])
                self.assertEqual(report["checks"][0]["status"], "passed")
                self.assertEqual(report["diagnostics"][0]["line"], 2)
                self.assertEqual(report["diagnostics"][0]["severity"], "error")

    def test_warning_recovery_is_reported_without_failing(self):
        text = "Warning: singular matrix\nWarning: dynamic gmin stepping failed\nNote: Starting source stepping\nNote: source stepping completed\nx = 1"
        report = check_log(text, spec(x={"min": 0}))
        self.assertTrue(report["passed"])
        self.assertEqual([item["severity"] for item in report["diagnostics"]], ["warning", "warning"])

    def test_names_do_not_match_prefixes_and_unknown_values_are_ignored(self):
        report = check_log("xlong=999\nother=NaN\nx=1", spec(x={"min": 0}))
        self.assertTrue(report["passed"])
        self.assertEqual(report["checks"][0]["lineNumbers"], [3])

    def test_report_does_not_echo_log_or_modify_inputs(self):
        marker = "PRIVATE_NETLIST_PATH_AND_SECRET"
        text = f"Error: {marker}\nx = 1"
        report = check_log(text, spec(x={"min": 0}))
        self.assertNotIn(marker, json.dumps(report))
        self.assertFalse(report["passed"])
        report["limitations"].append("changed")
        self.assertNotIn("changed", check_log("x=1", spec(x={"min": 0}))["limitations"])

    def test_crlf_and_blank_lines_keep_line_numbers(self):
        report = check_log("\r\nunknown\r\nx = 1\r\nWarning: test\r\n", spec(x={"min": 0}))
        self.assertEqual(report["checks"][0]["lineNumbers"], [3])
        self.assertEqual(report["diagnostics"][0]["line"], 4)

    def test_log_input_type_utf8_and_size_are_bounded(self):
        for text in [None, b"x=1", "\ud800", "x" * (MAX_LOG_BYTES + 1)]:
            with self.subTest(kind=type(text)), self.assertRaises(ValueError):
                check_log(text, spec(x={"min": 0}))


if __name__ == "__main__":
    unittest.main()
