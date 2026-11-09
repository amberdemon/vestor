"""Strict JSON boundary for the existing immutable domain input types."""
from dataclasses import MISSING, fields, is_dataclass
from datetime import date
from decimal import Decimal
from types import UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints

from vestor_domain.ani import AniInputs
from vestor_domain.primitives import InputError, parse_date, parse_gbp, parse_percent


def decode_input(raw: object) -> AniInputs:
    return cast(AniInputs, _decode(AniInputs, raw, "inputs"))


def _decode(kind: Any, raw: object, path: str) -> Any:
    origin, args = get_origin(kind), get_args(kind)
    if origin in (UnionType, Union):
        if raw is None and type(None) in args:
            return None
        return _decode(next(arg for arg in args if arg is not type(None)), raw, path)
    if is_dataclass(kind):
        if not isinstance(raw, dict):
            raise InputError(path, "Supply an object with labelled fields.")
        definitions = {field.name: field for field in fields(kind)}
        if raw.keys() - definitions.keys():
            raise InputError(path, "Remove unrecognised fields.")
        hints = get_type_hints(kind)
        values = {}
        for name, field in definitions.items():
            if name in raw:
                values[name] = _decode(hints[name], raw[name], f"{path}.{name}")
            elif field.default is MISSING and field.default_factory is MISSING:
                raise InputError(f"{path}.{name}", "Supply this field, or null where unknown is allowed.")
        try:
            return cast(Any, kind)(**values)
        except InputError as exc:
            raise InputError(f"{path}.{exc.field}", str(exc)) from None
    if origin is tuple:
        if not isinstance(raw, list):
            raise InputError(path, "Supply a list.")
        return tuple(_decode(args[0], item, f"{path}.{i}") for i, item in enumerate(raw))
    if origin is Literal:
        if raw not in args or type(raw) is not type(args[0]):
            raise InputError(path, "Select one of the supported options.")
        return raw
    if kind is Decimal:
        try:
            return parse_percent(raw) if path.endswith("percent") else parse_gbp(raw)
        except InputError as exc:
            raise InputError(path, str(exc)) from None
    if kind is date:
        return parse_date(raw, field=path)
    if kind in (str, bool, int) and type(raw) is kind:
        return raw
    raise InputError(path, "Use the required text, integer or boolean type; coercion is not supported.")


def error_field(field: str, payload: dict[str, Any]) -> str:
    """Translate domain keys/source identities into wire paths, never echo IDs.

    Some domain problems identify a whole collection or an evidence identity
    rather than a field path. Unassigned problems remain general form errors.
    """
    def visit(node: object, path: str) -> list[tuple[str, str, object]]:
        found: list[tuple[str, str, object]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}"
                found.append((child, key, value))
                found.extend(visit(value, child))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                found.extend(visit(value, f"{path}.{index}"))
        return found

    paths = visit(payload, "inputs")
    if any(path == field for path, _, _ in paths):
        return field
    if field in payload:
        return f"inputs.{field}"
    identities = {"event_id", "period_id", "reduction_id", "benefit_id", "pay_id", "component_id"}
    for path, key, value in paths:
        if key in identities and value == field:
            return path
    for path, key, _ in paths:
        if key == field:
            return path
    return "inputs"
