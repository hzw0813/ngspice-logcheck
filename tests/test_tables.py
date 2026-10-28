"""Tests for explicit scalar CSV normalization and same-context comparisons."""

import copy
import csv
import io
import json
import math
import unittest

from ngspice_logcheck.tables import MAX_TABLE_BYTES, compare_tables, load_table_spec

HEADER = ["test", "corner", "point", "measurement", "value", "unit", "status"]


def table(*rows, header=HEADER):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue()


def spec(*rows):
    return {"schemaVersion": 1, "measurements": list(rows) or [{"test": "tb", "corner": "tt", "point": "nominal", "measurement": "gain", "unit": "V/V", "min": 1, "max": 3}]}


def row(value="2", unit="V/V", status="ok", test="tb", corner="tt", point="nominal", measurement="gain"):
    return [test, corner, point, measurement, value, unit, status]


class TableSpecTests(unittest.TestCase):
    def test_valid_spec_json_normalizes_bounds_without_mutation(self):
        original = spec()
        loaded = load_table_spec(json.dumps(original))
        self.assertEqual(loaded, original)
        self.assertIs(type(loaded["measurements"][0]["min"]), float)
        loaded["measurements"][0]["min"] = 0
        self.assertEqual(original["measurements"][0]["min"], 1)

    def test_strict_json_duplicate_keys_nonfinite_and_underflow_rejected(self):
        valid = json.dumps(spec())
        cases = ["", "[", valid.replace('"schemaVersion": 1', '"schemaVersion":1,"schemaVersion":1'), valid.replace('"min": 1', '"min":1,"min":2'), valid.replace('"min": 1', '"min":NaN'), valid.replace('"min": 1', '"min":Infinity'), valid.replace('"min": 1', '"min":1e9999'), valid.replace('"min": 1', '"min":1e-9999')]
        for text in cases:
            with self.subTest(kind=text[:20]), self.assertRaises(ValueError):
                load_table_spec(text)

    def test_programmatic_schema_keys_types_and_bounds_revalidated(self):
        valid = spec()
        cases = [None, [], {}, {**valid, "schemaVersion": True}, {**valid, "schemaVersion": 1.0}, {**valid, "schemaVersion": 2}, {**valid, "extra": "raw"}, {"schemaVersion": 1, "measurements": []}, {"schemaVersion": 1, "measurements": {}}, spec({**valid["measurements"][0], "min": True}), spec({**valid["measurements"][0], "max": math.inf}), spec({**valid["measurements"][0], "min": 10**10000}), spec({**valid["measurements"][0], "min": 4}), spec({**valid["measurements"][0], "extra": 1})]
        for field in ["test", "corner", "point", "measurement", "unit"]:
            item = dict(valid["measurements"][0])
            del item[field]
            cases.append(spec(item))
        cases.append(spec({key: value for key, value in valid["measurements"][0].items() if key not in ("min", "max")}))
        cases.append(spec(*[dict(valid["measurements"][0]) for _ in range(1001)]))
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                compare_tables(table(row()), table(row()), value)

    def test_identity_duplicates_rejected_but_case_sensitive_labels_distinct(self):
        item = spec()["measurements"][0]
        with self.assertRaisesRegex(ValueError, "unique"):
            compare_tables(table(row()), table(row()), spec(item, {**item, "unit": "v/v"}))
        two = spec(item, {**item, "test": "TB"})
        result = compare_tables(table(row(), row(test="TB")), table(row(), row(test="TB")), two)
        self.assertTrue(result["passed"])


class TableComparisonTests(unittest.TestCase):
    def test_candidate_limits_and_signed_descriptive_delta(self):
        original = spec()
        preserved = copy.deepcopy(original)
        result = compare_tables(table(row("2")), table(row("4")), original)
        self.assertFalse(result["passed"])
        self.assertTrue(result["baselinePassed"])
        self.assertEqual(result["regressions"], 1)
        self.assertEqual(result["improvements"], 0)
        cell = result["rows"][0]
        self.assertEqual(cell["delta"], 2)
        self.assertEqual(cell["relativeDelta"], 1)
        self.assertEqual(cell["candidateReason"], "above-maximum")
        self.assertEqual(cell["candidateRows"], [2])
        self.assertEqual(original, preserved)
        self.assertEqual(result["kind"], "normalized-scalar-comparison")
        self.assertTrue(compare_tables(table(row("4")), table(row("2")), original)["passed"])
        self.assertEqual(compare_tables(table(row("4")), table(row("2")), original)["improvements"], 1)

    def test_corners_points_tests_and_same_metric_do_not_merge(self):
        base = spec()["measurements"][0]
        selected = spec(base, {**base, "corner": "ff"}, {**base, "point": "iteration-7"}, {**base, "test": "other"})
        baseline = table(row(), row(corner="ff"), row(point="iteration-7"), row(test="other"))
        candidate = table(row("2"), row("4", corner="ff"), row("2", point="iteration-7"), row("2", test="other"))
        result = compare_tables(baseline, candidate, selected)
        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual([item["candidateStatus"] for item in result["rows"]], ["passed", "failed", "passed", "passed"])

    def test_units_are_exact_and_mismatch_suppresses_values_and_deltas(self):
        for unit in ["v/v", "mV/V", "A"]:
            result = compare_tables(table(row()), table(row("2", unit=unit)), spec())
            cell = result["rows"][0]
            self.assertFalse(result["passed"])
            self.assertEqual(cell["candidateReason"], "unit-mismatch")
            self.assertIsNone(cell["candidateValue"])
            self.assertIsNone(cell["delta"])
            self.assertIsNone(cell["relativeDelta"])

    def test_missing_duplicate_and_failed_observations_fail_without_values(self):
        for candidate, reason, refs in [(table(), "missing-observation", []), (table(row(), row()), "ambiguous-duplicates", [2, 3]), (table(row("", status="failed")), "exporter-failed", [2])]:
            with self.subTest(reason=reason):
                result = compare_tables(table(row()), candidate, spec())
                cell = result["rows"][0]
                self.assertFalse(result["passed"])
                self.assertEqual(cell["candidateReason"], reason)
                self.assertEqual(cell["candidateRows"], refs)
                self.assertIsNone(cell["candidateValue"])
                self.assertIsNone(cell["delta"])

    def test_invalid_ok_values_fail_instead_of_disappearing(self):
        for value in ["", "NaN", "Infinity", "1e9999", "1e-9999", "1e-999999999999999999999", "1m", "1 e-3", "1e3junk", "2 V/V", " 2", "2 ", "true", "0x10"]:
            with self.subTest(value=value):
                result = compare_tables(table(row()), table(row(value)), spec())
                cell = result["rows"][0]
                self.assertFalse(result["passed"])
                self.assertEqual(cell["candidateReason"], "invalid-value")
                self.assertEqual(cell["candidateRows"], [2])
                self.assertIsNone(cell["candidateValue"])
                json.dumps(result, allow_nan=False)

    def test_unknown_context_and_invalid_status_fail_structural_normalization(self):
        for candidate in [table(row(corner="FF")), table(row(point="unknown")), table(row(measurement="GAIN")), table(row(status="OK")), table(row("2", status="failed")), table(row(" ", status="failed"))]:
            with self.assertRaises(ValueError):
                compare_tables(table(row()), candidate, spec())

    def test_exact_header_set_any_order_and_bad_headers_or_widths_rejected(self):
        permuted = ["status", "unit", "value", "measurement", "point", "corner", "test"]
        result = compare_tables(table(row()), table(list(reversed(row())), header=permuted), spec())
        self.assertTrue(result["passed"])
        for candidate in ["", "\n\n", table(row(), header=HEADER[:-1]), table(row(), header=HEADER + ["extra"]), table(row(), header=["test"] + HEADER[1:-1] + ["test"]), table(row(), header=["Test"] + HEADER[1:]), table(row()[:-1]), table(row() + ["extra"])]:
            with self.subTest(header=candidate[:30]), self.assertRaises(ValueError):
                compare_tables(table(row()), candidate, spec())

    def test_quoted_commas_escaped_quotes_unicode_and_record_end_lines(self):
        label = 'tb, "測試"'
        unit = "µA"
        item = {**spec()["measurements"][0], "test": label, "unit": unit}
        text = "\n" + table(row(test=label, unit=unit)).replace("\n", "\r\n") + "\r\n"
        result = compare_tables(text, text, spec(item))
        self.assertTrue(result["passed"])
        self.assertEqual(result["rows"][0]["test"], label)
        self.assertEqual(result["rows"][0]["baselineRows"], [3])

    def test_malformed_quotes_controls_whitespace_and_label_bounds_rejected(self):
        for value in ["", " tb", "tb ", "tb\tbad", "tb\x00bad", "tb\nbad", "tb\u200bbad", "x" * 129]:
            with self.subTest(label=repr(value)), self.assertRaises(ValueError):
                # Python 3.10's writer rejects NUL before the reader under test.
                candidate = table(row()).replace("\ntb,", "\n" + value + ",", 1) if "\x00" in value else table(row(test=value))
                compare_tables(table(row()), candidate, spec())
        for unit in ["", " V/V", "V/V ", "x" * 33, "V\nV"]:
            with self.subTest(unit=repr(unit)), self.assertRaises(ValueError):
                compare_tables(table(row()), table(row(unit=unit)), spec())
        header = ",".join(HEADER) + "\n"
        for record in ['"tb,tt,nominal,gain,2,V/V,ok', 'tb"bad,tt,nominal,gain,2,V/V,ok', '"tb"junk,tt,nominal,gain,2,V/V,ok', '"tb" ,tt,nominal,gain,2,V/V,ok']:
            with self.subTest(record=record), self.assertRaises(ValueError):
                compare_tables(table(row()), header + record, spec())

    def test_numeric_zero_negative_bounds_and_arithmetic_overflow(self):
        zero_spec = spec({**spec()["measurements"][0], "min": -1, "max": 3})
        cell = compare_tables(table(row("0")), table(row("1")), zero_spec)["rows"][0]
        self.assertEqual(cell["delta"], 1)
        self.assertIsNone(cell["relativeDelta"])
        bounds = spec({**spec()["measurements"][0], "min": -1.7e308, "max": 1.7e308})
        report = compare_tables(table(row("-1e308")), table(row("1e308")), bounds)
        self.assertIsNone(report["rows"][0]["delta"])
        self.assertIn("delta-overflow", report["rows"][0]["notes"])
        ratio = compare_tables(table(row("1e-308")), table(row("1e308")), bounds)
        self.assertIsNone(ratio["rows"][0]["relativeDelta"])
        json.dumps(report, allow_nan=False)
        json.dumps(ratio, allow_nan=False)

    def test_input_and_row_limits_invalid_utf8_and_no_raw_excerpt_errors(self):
        for text in [None, b"raw", "\ud800", "x" * (MAX_TABLE_BYTES + 1), table(*[row() for _ in range(10_001)])]:
            with self.subTest(kind=type(text)), self.assertRaises(ValueError):
                compare_tables(table(row()), text, spec())
        try:
            compare_tables(table(row()), table(row(test="PRIVATE_CONTEXT")), spec())
        except ValueError as error:
            self.assertNotIn("PRIVATE_CONTEXT", str(error))
        else:
            self.fail("Unexpected contexts must fail.")


if __name__ == "__main__":
    unittest.main()
