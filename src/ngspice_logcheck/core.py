"""Bounded, declarative checks of already-produced ngspice text logs.

This module does not run a simulator, evaluate expressions, or attest where a
log came from. It deliberately accepts a narrow scalar-output grammar.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_SPEC_BYTES = 1024 * 1024
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_NAME_RE = re.compile(_NAME, re.ASCII)
_ASSIGNMENT = re.compile(rf"^[ \t]*({_NAME})[ \t]*=[ \t]*(.*)$", re.ASCII)
_VALUE = re.compile(rf"({_NUMBER})(.*)", re.ASCII)
_METADATA = re.compile(rf"[ \t]+(at|from|to|trig|targ|with)[ \t]*=[ \t]*({_NUMBER})", re.ASCII | re.IGNORECASE)
_QUOTED_FAILURE = re.compile(rf"\bmeasure(?:ment)?[ \t]+(?:['\"]({_NAME})['\"]|({_NAME}))[ \t]+failed\b", re.ASCII | re.IGNORECASE)
_COMMAND_FAILURE = re.compile(rf"^[ \t]*\.?meas(?:ure)?[ \t]+(?:dc|ac|tran|sp)[ \t]+({_NAME})\b.*\bfailed\b", re.ASCII | re.IGNORECASE)
_FATAL = re.compile(r"^[ \t]*(?:fatal(?:[ \t]+error)?(?=[:( \t])|\*{2,}[ \t]*fatal(?:[ \t]+error)?(?:[ \t]*:|[ \t]*\*{2,}))", re.ASCII | re.IGNORECASE)
_ERROR = re.compile(r"^[ \t]*(?:error(?=[:( \t])|\*{2,}[ \t]*error(?:[ \t]*:|[ \t]*\*{2,}))", re.ASCII | re.IGNORECASE)
_WARNING = re.compile(r"^[ \t]*(?:warning[ \t]*:|\*{2,}[ \t]*warning(?:[ \t]*:|[ \t]*\*{2,}))", re.ASCII | re.IGNORECASE)

_LIMITATIONS = [
    "Only requested scalar assignments and a documented subset of ngspice diagnostics are recognized; arbitrary other lines are ignored.",
    "A passing result means the supplied text contains one finite in-range value for every requested name and no recognized error; it does not establish completed, fresh, authentic, or correct simulation.",
    "An echoed or let-generated assignment is indistinguishable from a measurement result in plain text. No simulator banner, source provenance, run identity, units, waveform, circuit, or process exit status is verified.",
    "Measurement names are matched case-insensitively. Duplicate assignments fail even when their numbers agree; concatenated runs and parameter sweeps require separate input logs.",
    "Values use decimal or e/E scientific notation without SPICE scale suffixes. Optional finite numeric metadata is restricted to at/from/to/trig/targ/with; other output dialects fail for requested assignments.",
    "Numbers are compared as Python binary64 floats; overflow and nonzero decimal underflow to zero are rejected when parsing text. Normal binary64 rounding still applies.",
    "Warnings are reported without failing the result. Diagnostic recognition is incomplete and cannot prove that an ignored line is harmless.",
    "Reports retain requested names, bounds, scalar values, line numbers and fixed diagnostic codes, but no raw log excerpts. Line 0 denotes an input-level diagnostic without a physical source line.",
]


def _bounded_text(text: str, maximum: int, label: str) -> None:
    if not isinstance(text, str):
        raise ValueError(f"{label} must be text.")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text.") from exc
    if size > maximum:
        raise ValueError(f"{label} exceeds the supported byte limit.")


def _finite_bound(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Measurement limits must be finite JSON numbers.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Measurement limits must be finite JSON numbers.") from exc
    if not math.isfinite(number):
        raise ValueError("Measurement limits must be finite JSON numbers.")
    return number


def _validate_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) != {"schemaVersion", "measurements"}:
        raise ValueError("Spec must contain only schemaVersion and measurements.")
    if type(spec["schemaVersion"]) is not int or spec["schemaVersion"] != 1:
        raise ValueError("schemaVersion must be integer 1.")
    measurements = spec["measurements"]
    if not isinstance(measurements, dict) or not 1 <= len(measurements) <= 1000:
        raise ValueError("measurements must be an object with 1 to 1000 entries.")
    normalized: dict[str, dict[str, float]] = {}
    seen: set[str] = set()
    for name, limits in measurements.items():
        if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
            raise ValueError("Measurement names must use ASCII letters, digits and underscores, and start with a letter or underscore.")
        folded = name.casefold()
        if folded in seen:
            raise ValueError("Measurement names must be unique without regard to case.")
        seen.add(folded)
        if not isinstance(limits, dict) or not limits or not set(limits).issubset({"min", "max"}):
            raise ValueError("Each measurement requires only min and/or max limits.")
        bounds = {key: _finite_bound(value) for key, value in limits.items()}
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise ValueError("Measurement min must not exceed max.")
        normalized[name] = bounds
    return {"schemaVersion": 1, "measurements": normalized}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not allowed.")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON constants are not allowed.")


def _token_float(token: str) -> float:
    try:
        number = float(token)
        underflowed = number == 0 and Decimal(token) != 0
    except (ValueError, OverflowError, InvalidOperation) as exc:
        raise ValueError("Numbers must be representable as finite, non-underflowing binary64 values.") from exc
    if not math.isfinite(number) or underflowed:
        raise ValueError("Numbers must be representable as finite, non-underflowing binary64 values.")
    return number


def load_spec(text: str) -> dict[str, Any]:
    """Parse and validate version-1 JSON limits; return an independent copy.

    Duplicate JSON keys at every depth and case-insensitive duplicate
    measurement names are rejected. Invalid input raises ``ValueError``.
    """
    _bounded_text(text, MAX_SPEC_BYTES, "Spec")
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_token_float)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("Spec must be valid JSON without duplicate keys or non-finite constants.") from exc
    return _validate_spec(value)


def _parse_value(body: str) -> float | None:
    """Accept one complete numeric token followed only by known metadata."""
    match = _VALUE.fullmatch(body.rstrip(" \t"))
    if match is None:
        return None
    try:
        number = _token_float(match.group(1))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    tail = match.group(2)
    position = 0
    seen: set[str] = set()
    while position < len(tail):
        metadata = _METADATA.match(tail, position)
        if metadata is None or metadata.group(1).casefold() in seen:
            return None
        seen.add(metadata.group(1).casefold())
        try:
            _token_float(metadata.group(2))
        except ValueError:
            return None
        position = metadata.end()
    return number


def check_log(text: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Check supplied text against limits without executing any code.

    Invalid/oversized inputs raise ``ValueError``; recognized log failures
    return a report with ``passed=False``. The spec is validated even when
    supplied directly rather than through :func:`load_spec`.
    """
    _bounded_text(text, MAX_LOG_BYTES, "Log")
    validated = _validate_spec(spec)
    requested = validated["measurements"]
    requested_by_fold = {name.casefold(): name for name in requested}
    observations: dict[str, list[tuple[int, float | None]]] = {name: [] for name in requested}
    named_failures: dict[str, list[int]] = {name: [] for name in requested}
    diagnostics: list[dict[str, Any]] = []
    if not text.strip():
        diagnostics.append({"line": 0, "severity": "error", "code": "empty-log"})

    for line_number, line in enumerate(text.splitlines(), 1):
        assignment = _ASSIGNMENT.fullmatch(line)
        if assignment is not None:
            name = requested_by_fold.get(assignment.group(1).casefold())
            if name is not None:
                observations[name].append((line_number, _parse_value(assignment.group(2))))

        failed_names: set[str] = set()
        for failure in _QUOTED_FAILURE.finditer(line):
            failed_names.add((failure.group(1) or failure.group(2)).casefold())
        for failure in _COMMAND_FAILURE.finditer(line):
            failed_names.add(failure.group(1).casefold())
        for folded in failed_names:
            name = requested_by_fold.get(folded)
            if name is not None:
                named_failures[name].append(line_number)

        lowered = line.casefold()
        code = None
        severity = "error"
        if failed_names:
            code = "measurement-failed"
        elif _FATAL.match(line):
            code = "ngspice-fatal-error"
        elif _ERROR.match(line):
            code = "ngspice-error"
        elif re.search(r"\bsimulation(?:s|\(s\))?[ \t]+aborted\b", lowered, re.ASCII):
            code = "simulation-aborted"
        elif re.search(r"\bsimulation(?:s|\(s\))?[ \t]+interrupted\b", lowered, re.ASCII):
            code = "simulation-interrupted"
        elif re.search(r"\btimestep[ \t]+too[ \t]+small\b", lowered, re.ASCII):
            code = "timestep-too-small"
        elif _WARNING.match(line):
            code = "ngspice-warning"
            severity = "warning"
        if code is not None:
            diagnostics.append({"line": line_number, "severity": severity, "code": code})

    checks = []
    for name, limits in requested.items():
        seen = observations[name]
        failures = named_failures[name]
        line_numbers = sorted({number for number, _ in seen}.union(failures))
        value = seen[0][1] if len(seen) == 1 else None
        if failures:
            reason = "measurement-failed"
        elif len(seen) > 1:
            reason = "ambiguous-duplicates"
        elif not seen:
            reason = "missing-measurement"
        elif value is None:
            reason = "invalid-value"
        elif "min" in limits and value < limits["min"]:
            reason = "below-minimum"
        elif "max" in limits and value > limits["max"]:
            reason = "above-maximum"
        else:
            reason = "within-limits"
        checks.append({
            "name": name, "status": "passed" if reason == "within-limits" else "failed",
            "value": value, "limits": dict(limits), "lineNumbers": line_numbers, "reason": reason,
        })
    passed = all(check["status"] == "passed" for check in checks) and not any(item["severity"] == "error" for item in diagnostics)
    return {"schemaVersion": 1, "passed": passed, "checks": checks, "diagnostics": diagnostics, "limitations": list(_LIMITATIONS)}
