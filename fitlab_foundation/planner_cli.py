"""Strict deterministic JSON/CLI boundary for the FitLab F2 planner."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .contracts import ArchitectureKind, AttentionMechanism, ModelArchitecture, Workload
from .planner import PlanningScenario, plan_hardware_to_workloads, plan_workload_to_hardware
from .serialization import canonical_json
from .validation import ValidationError

MAX_INPUT_BYTES = 1024 * 1024
MAX_SCENARIOS = 50
MAX_INPUT_DEPTH = 32
MAX_NUMBER_CHARACTERS = 100
MAX_DECIMAL_CHARACTERS = 256

_ROOT_KEYS = {"schema_version", "direction", "scenarios"}
_SCENARIO_KEYS = {
    "scenario_id",
    "model",
    "workload",
    "weight_bits_per_parameter",
    "explicit_runtime_overhead_bytes",
    "runtime_overhead_basis",
    "planning_memory_budget_bytes",
}
_MODEL_KEYS = {
    "model_id",
    "total_parameters",
    "active_parameters",
    "layers",
    "query_heads",
    "kv_heads",
    "head_dimension",
    "architecture_kind",
    "attention_mechanism",
}
_WORKLOAD_KEYS = {
    "resident_sequences",
    "cached_tokens_per_sequence",
    "kv_bytes_per_element",
    "target_tokens_per_second",
    "declared_bytes_reloaded_per_token",
    "residency_assumption",
}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise ValidationError("INVALID_TYPE", field, "expected JSON object with string keys")
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], required: set[str], field: str) -> None:
    missing = sorted(required - value.keys())
    unexpected = sorted(value.keys() - allowed)
    if missing:
        raise ValidationError("MISSING_FIELD", field, "missing: " + ",".join(missing))
    if unexpected:
        raise ValidationError("UNEXPECTED_FIELD", field, "unexpected field name")


def _decimal_text(value: Any, field: str) -> Decimal:
    if type(value) is not str or not value:
        raise ValidationError("INVALID_TYPE", field, "expected nonempty decimal string")
    if len(value) > MAX_DECIMAL_CHARACTERS:
        raise ValidationError("DECIMAL_COMPLEXITY", field, "decimal text exceeds 256 characters")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError("INVALID_DECIMAL", field, "invalid decimal text") from exc
    if not result.is_finite():
        raise ValidationError("NON_FINITE", field, "decimal must be finite")
    return result


def _optional_int(value: dict[str, Any], name: str) -> int | None:
    item = value.get(name)
    if item is None:
        return None
    if type(item) is not int:
        raise ValidationError("INVALID_TYPE", name, "expected exact integer")
    return item


def _optional_text(value: dict[str, Any], name: str) -> str | None:
    item = value.get(name)
    if item is None:
        return None
    if type(item) is not str:
        raise ValidationError("INVALID_TYPE", name, "expected string")
    return item


def _enum(enum_type, value: Any, field: str):
    if type(value) is not str:
        raise ValidationError("INVALID_TYPE", field, "expected enum string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValidationError("UNSUPPORTED_VALUE", field, "unsupported enum value") from exc


def _parse_scenario(raw: Any) -> PlanningScenario:
    scenario = _mapping(raw, "scenario")
    _exact_keys(
        scenario,
        _SCENARIO_KEYS,
        {"scenario_id", "model", "workload", "weight_bits_per_parameter"},
        "scenario",
    )
    model = _mapping(scenario["model"], "model")
    _exact_keys(model, _MODEL_KEYS, {"model_id", "total_parameters"}, "model")
    workload = _mapping(scenario["workload"], "workload")
    _exact_keys(workload, _WORKLOAD_KEYS, set(), "workload")
    if type(model["model_id"]) is not str:
        raise ValidationError("INVALID_TYPE", "model_id", "expected string")
    if type(model["total_parameters"]) is not int:
        raise ValidationError("INVALID_TYPE", "total_parameters", "expected exact integer")
    if type(scenario["scenario_id"]) is not str:
        raise ValidationError("INVALID_TYPE", "scenario_id", "expected string")

    target = workload.get("target_tokens_per_second")
    return PlanningScenario(
        scenario_id=scenario["scenario_id"],
        model=ModelArchitecture(
            model_id=model["model_id"],
            total_parameters=model["total_parameters"],
            active_parameters=_optional_int(model, "active_parameters"),
            layers=_optional_int(model, "layers"),
            query_heads=_optional_int(model, "query_heads"),
            kv_heads=_optional_int(model, "kv_heads"),
            head_dimension=_optional_int(model, "head_dimension"),
            architecture_kind=_enum(
                ArchitectureKind,
                model.get("architecture_kind", "UNKNOWN"),
                "architecture_kind",
            ),
            attention_mechanism=_enum(
                AttentionMechanism,
                model.get("attention_mechanism", "UNKNOWN"),
                "attention_mechanism",
            ),
        ),
        workload=Workload(
            resident_sequences=workload.get("resident_sequences", 1),
            cached_tokens_per_sequence=_optional_int(workload, "cached_tokens_per_sequence"),
            kv_bytes_per_element=_optional_int(workload, "kv_bytes_per_element"),
            target_tokens_per_second=(
                None if target is None else _decimal_text(target, "target_tokens_per_second")
            ),
            declared_bytes_reloaded_per_token=_optional_int(
                workload, "declared_bytes_reloaded_per_token"
            ),
            residency_assumption=_optional_text(workload, "residency_assumption"),
        ),
        weight_bits_per_parameter=_decimal_text(
            scenario["weight_bits_per_parameter"], "weight_bits_per_parameter"
        ),
        explicit_runtime_overhead_bytes=_optional_int(
            scenario, "explicit_runtime_overhead_bytes"
        ),
        runtime_overhead_basis=_optional_text(scenario, "runtime_overhead_basis"),
        planning_memory_budget_bytes=_optional_int(scenario, "planning_memory_budget_bytes"),
    )


def run_document(raw: Any) -> dict[str, Any]:
    document = _mapping(raw, "document")
    _exact_keys(document, _ROOT_KEYS, _ROOT_KEYS, "document")
    if document["schema_version"] != 1 or type(document["schema_version"]) is not int:
        raise ValidationError("UNSUPPORTED_SCHEMA", "schema_version", "expected exact integer 1")
    direction = document["direction"]
    if type(direction) is not str or direction not in {"workload_to_hardware", "hardware_to_workloads"}:
        raise ValidationError("UNSUPPORTED_VALUE", "direction", "unsupported planning direction")
    raw_scenarios = document["scenarios"]
    if type(raw_scenarios) is not list or not raw_scenarios:
        raise ValidationError("INVALID_TYPE", "scenarios", "expected nonempty JSON array")
    if len(raw_scenarios) > MAX_SCENARIOS:
        raise ValidationError(
            "MAX_ITEMS_EXCEEDED",
            "scenarios",
            f"maximum scenario count is {MAX_SCENARIOS}",
        )
    scenarios = tuple(_parse_scenario(item) for item in raw_scenarios)
    identifiers = [scenario.scenario_id for scenario in scenarios]
    if len(set(identifiers)) != len(identifiers):
        raise ValidationError("DUPLICATE_IDENTITY", "scenario_id", "scenario IDs must be unique")
    if direction == "workload_to_hardware":
        results = tuple(plan_workload_to_hardware(scenario) for scenario in scenarios)
    else:
        results = plan_hardware_to_workloads(scenarios)
    return {"schema_version": 1, "direction": direction, "results": results}


def _error_document(code: str, field: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "ERROR",
        "error": {"code": code, "field": field, "detail": detail},
    }


def _check_json_depth(text: str) -> None:
    """Bound parser recursion before parsing, ignoring escaped string contents."""
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_INPUT_DEPTH:
                raise ValidationError("MAX_DEPTH_EXCEEDED", "input", "maximum JSON depth is 32")
        elif char in "]}":
            depth -= 1


def _parse_integer(token: str) -> int:
    if len(token) > MAX_NUMBER_CHARACTERS:
        raise ValidationError("NUMBER_TOO_LONG", "input", "maximum integer token length is 100")
    return int(token)


def _reject_number(token: str) -> None:
    raise ValidationError("INVALID_NUMBER", "input", "use exact integers or decimal strings")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("DUPLICATE_KEY", "input", "duplicate object keys are forbidden")
        result[key] = value
    return result


def _read_bounded_document(path: Path) -> Any:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as exc:
        raise ValidationError("INPUT_IO_ERROR", "input", exc.__class__.__name__) from exc
    if len(payload) > MAX_INPUT_BYTES:
        raise ValidationError(
            "INPUT_TOO_LARGE",
            "input",
            f"maximum UTF-8 input is {MAX_INPUT_BYTES} bytes",
        )
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("INVALID_UTF8", "input", "input must be strict UTF-8") from exc
    try:
        _check_json_depth(text)
        return json.loads(text, parse_int=_parse_integer, parse_float=_reject_number,
                          parse_constant=_reject_number, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "INVALID_JSON",
            "input",
            f"invalid JSON at line {exc.lineno} column {exc.colno}",
        ) from exc

    except (ValueError, RecursionError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("INVALID_JSON", "input", "JSON exceeds parser bounds") from exc


def _render_error(exc: ValidationError) -> str:
    # Errors must not recursively depend on serializing hostile input.
    def safe(value: str) -> str:
        return value[:256].encode("ascii", "backslashreplace").decode("ascii")[:1024]
    return json.dumps(_error_document(safe(exc.code), safe(exc.field), safe(exc.message)),
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic FitLab F2 planner")
    parser.add_argument("--input", required=True, help="Path to a UTF-8 JSON request")
    arguments = parser.parse_args(argv)
    try:
        raw = _read_bounded_document(Path(arguments.input))
        output = run_document(raw)
        rendered = canonical_json(output)
    except ValidationError as exc:
        print(_render_error(exc))
        return 2
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
