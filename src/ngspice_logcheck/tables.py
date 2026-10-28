"""Compare explicitly normalized scalar CSV tables under one shared limits spec.

This is a documented interchange format, not a native Cadence ADE/Spectre
export reader. Exporters must map their own contexts, measurements and units.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from .compare import _deltas
from .core import MAX_SPEC_BYTES, _bounded_text, _finite_bound, _reject_constant, _token_float, _unique_object

MAX_TABLE_BYTES = 16 * 1024 * 1024
MAX_TABLE_ROWS = 10_000
_IDENTITY_FIELDS = ("test", "corner", "point", "measurement")
_COLUMNS = {"test", "corner", "point", "measurement", "value", "unit", "status"}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_LIMITATIONS = [
    "Inputs are explicitly normalized scalar tables, not native Cadence ADE/Spectre exports. Exporter column mapping and a real ADE integration are outside this tool; no simulator, shell, or exporter is executed.",
    "Identity is the exact case-sensitive tuple (test, corner, point, measurement). Exporters must supply an explicit point label for nominal, sweep, or iteration context; context is never inferred.",
    "Only identities declared in the shared spec are checked. Missing selected identities fail, unexpected CSV identities are rejected, and passing selected values do not establish complete test/corner/sweep coverage.",
    "Units are exact explicit case-sensitive labels. No unit inference, scaling or conversion is performed; a mismatched unit fails that observation and suppresses its scalar value and deltas.",
    "The ok/failed status is an exporter declaration, not independently observed simulator completion. A passing comparison does not authenticate data, establish freshness, prove circuit correctness, or constitute signoff.",
    "Values and limits use Python binary64 floats. Non-finite values, overflow and nonzero decimal underflow to zero are rejected while parsing text; ordinary binary64 rounding still applies.",
    "delta is candidate minus baseline in native units. relativeDelta is delta/baseline as a ratio, not a percentage; null values and fixed notes identify missing values, zero baseline, or arithmetic bounds.",
    "Regression/improvement means crossing the same declared limits from pass to fail or fail to pass. Numeric deltas are descriptive; no additional performance-regression threshold is inferred.",
    "Duplicate observations fail even when values agree. Invalid, failed, missing, ambiguous or unit-mismatched observations have null scalar values and no numeric deltas.",
    "CSV row references use csv.reader.line_num: the physical line where the record ends. Quoted multiline labels are rejected as control-containing labels; escaped quotes and commas in printable labels are supported.",
    "Reports retain explicit labels, units, limits, scalar values and record line numbers, but no raw CSV excerpts. Output labels can themselves be sensitive; review artifacts before sharing.",
]


def _label(value: Any, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip() or not value.isprintable():
        raise ValueError("Normalized labels must be bounded printable text without surrounding whitespace or control characters.")
    return value


def _identity(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(_label(row[key], 128) for key in _IDENTITY_FIELDS)


def _validate_table_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) != {"schemaVersion", "measurements"}:
        raise ValueError("Table spec requires only schemaVersion and measurements.")
    if type(spec["schemaVersion"]) is not int or spec["schemaVersion"] != 1:
        raise ValueError("Table spec schemaVersion must be integer 1.")
    rows = spec["measurements"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("Table spec measurements must contain 1 to 1000 entries.")
    normalized = []
    seen = set()
    required = set(_IDENTITY_FIELDS) | {"unit"}
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row) or not set(row).issubset(required | {"min", "max"}) or not set(row).intersection({"min", "max"}):
            raise ValueError("Table spec entries require exactly identity labels, unit, and min and/or max.")
        identity = _identity(row)
        if identity in seen:
            raise ValueError("Table spec identities must be unique.")
        seen.add(identity)
        unit = _label(row["unit"], 32)
        limits = {key: _finite_bound(row[key]) for key in ("min", "max") if key in row}
        if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
            raise ValueError("Table spec min must not exceed max.")
        normalized.append({**dict(zip(_IDENTITY_FIELDS, identity)), "unit": unit, **limits})
    return {"schemaVersion": 1, "measurements": normalized}


def load_table_spec(text: str) -> dict[str, Any]:
    """Parse strict version-1 JSON table limits, rejecting duplicate keys."""
    _bounded_text(text, MAX_SPEC_BYTES, "Table spec")
    try:
        parsed = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_token_float)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Table spec must be valid JSON without duplicate keys or unsupported numbers.") from exc
    return _validate_table_spec(parsed)


def _validate_csv_quotes(text: str) -> None:
    """Enforce quote boundaries that csv.reader(strict=True) leaves permissive."""
    quoted = False
    closed = False
    field_start = True
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 1
                else:
                    quoted = False
                    closed = True
        elif closed:
            if char in ",\r\n":
                closed = False
                field_start = True
            else:
                raise ValueError("CSV quoting is malformed; normalize the export explicitly.")
        elif char == '"':
            if not field_start:
                raise ValueError("CSV quoting is malformed; normalize the export explicitly.")
            quoted = True
            field_start = False
        elif char in ",\r\n":
            field_start = True
        else:
            field_start = False
        index += 1
    if quoted:
        raise ValueError("CSV quoting is malformed; normalize the export explicitly.")


def _parse_table(text: str, selected: set[tuple[str, str, str, str]]) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    _bounded_text(text, MAX_TABLE_BYTES, "CSV table")
    _validate_csv_quotes(text)
    observations = {identity: [] for identity in selected}
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"', strict=True)
    header = None
    records = 0
    try:
        for values in reader:
            if not values:
                continue  # Truly empty physical records do not declare an observation.
            if header is None:
                if len(values) != len(_COLUMNS) or set(values) != _COLUMNS:
                    raise ValueError("CSV requires the exact canonical header columns without duplicates or extra fields.")
                header = values
                continue
            records += 1
            if records > MAX_TABLE_ROWS:
                raise ValueError("CSV table exceeds the supported row limit.")
            if len(values) != len(header):
                raise ValueError("CSV record width does not match the canonical header.")
            row = dict(zip(header, values))
            identity = _identity(row)
            unit = _label(row["unit"], 32)
            if row["status"] not in ("ok", "failed"):
                raise ValueError("CSV status must be exactly ok or failed.")
            if row["status"] == "failed" and row["value"] != "":
                raise ValueError("A failed CSV observation must have an empty value field.")
            if identity not in selected:
                raise ValueError("CSV tables are incomparable: unexpected identities; normalize selected contexts explicitly.")
            number = None
            if row["status"] == "ok" and _NUMBER.fullmatch(row["value"]) is not None:
                try:
                    number = _token_float(row["value"])
                except ValueError:
                    pass  # Invalid selected observations fail rather than disappearing.
            observations[identity].append({"row": reader.line_num, "unit": unit, "status": row["status"], "value": number})
    except csv.Error as exc:
        raise ValueError("CSV structure is malformed or a field exceeds the parser bound.") from exc
    if header is None:
        raise ValueError("CSV requires the canonical header.")
    return observations


def _observation(records: list[dict[str, Any]], unit: str, limits: dict[str, float]) -> dict[str, Any]:
    rows = [record["row"] for record in records]
    number = None
    if not records:
        reason = "missing-observation"
    elif len(records) != 1:
        reason = "ambiguous-duplicates"
    elif records[0]["unit"] != unit:
        reason = "unit-mismatch"
    elif records[0]["status"] == "failed":
        reason = "exporter-failed"
    elif records[0]["value"] is None:
        reason = "invalid-value"
    else:
        number = records[0]["value"]
        if "min" in limits and number < limits["min"]:
            reason = "below-minimum"
        elif "max" in limits and number > limits["max"]:
            reason = "above-maximum"
        else:
            reason = "within-limits"
    return {"value": number, "rows": rows, "reason": reason, "status": "passed" if reason == "within-limits" else "failed"}


def compare_tables(baseline_text: str, candidate_text: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Compare normalized tables under unchanged explicit identities/units/limits.

    Structural normalization/spec errors raise ValueError without copying data.
    Missing, ambiguous, failed, invalid, unit-mismatched or out-of-bound selected
    observations produce failed checks in an otherwise inspectable report.
    """
    validated = _validate_table_spec(spec)
    selected = {_identity(row) for row in validated["measurements"]}
    baseline = _parse_table(baseline_text, selected)
    candidate = _parse_table(candidate_text, selected)
    rows = []
    for selected_row in validated["measurements"]:
        identity = _identity(selected_row)
        limits = {key: selected_row[key] for key in ("min", "max") if key in selected_row}
        before = _observation(baseline[identity], selected_row["unit"], limits)
        after = _observation(candidate[identity], selected_row["unit"], limits)
        delta, relative, notes = _deltas(before["value"], after["value"])
        rows.append({
            **dict(zip(_IDENTITY_FIELDS, identity)), "unit": selected_row["unit"], "limits": limits,
            "baselineValue": before["value"], "candidateValue": after["value"],
            "baselineStatus": before["status"], "candidateStatus": after["status"],
            "baselineReason": before["reason"], "candidateReason": after["reason"],
            "baselineRows": before["rows"], "candidateRows": after["rows"],
            "delta": delta, "relativeDelta": relative,
            "regressed": before["status"] == "passed" and after["status"] == "failed",
            "improved": before["status"] == "failed" and after["status"] == "passed",
            "notes": notes,
        })
    return {
        "schemaVersion": 1, "kind": "normalized-scalar-comparison",
        "passed": all(row["candidateStatus"] == "passed" for row in rows),
        "baselinePassed": all(row["baselineStatus"] == "passed" for row in rows),
        "regressions": sum(row["regressed"] for row in rows), "improvements": sum(row["improved"] for row in rows),
        "rows": rows, "limitations": list(_LIMITATIONS),
    }
