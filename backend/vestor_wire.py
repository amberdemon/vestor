"""Strict JSON boundary for the existing immutable domain input types."""
from dataclasses import MISSING, fields, is_dataclass
from datetime import date
from fractions import Fraction
import re
from decimal import Decimal
from types import UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints

from vestor_domain.ani import AniInputs, AniResult
from vestor_domain.m2 import M2Inputs, M2Result
from vestor_domain.primitives import InputError, display_gbp, parse_date, parse_gbp, parse_percent
from vestor_domain.settlement import PayrollSettlement


def decode_input(raw: object) -> AniInputs:
    return cast(AniInputs, _decode(AniInputs, raw, "inputs"))


def decode_m2_input(raw: object) -> M2Inputs:
    return cast(M2Inputs, _decode(M2Inputs, raw, "inputs", m2=True))


def _decode(kind: Any, raw: object, path: str, *, m2: bool = False) -> Any:
    origin, args = get_origin(kind), get_args(kind)
    if origin in (UnionType, Union):
        if raw is None and type(None) in args:
            return None
        return _decode(next(arg for arg in args if arg is not type(None)), raw, path, m2=m2)
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
                values[name] = _decode(hints[name], raw[name], f"{path}.{name}", m2=m2)
            elif field.default is MISSING and field.default_factory is MISSING:
                raise InputError(f"{path}.{name}", "Supply this field, or null where unknown is allowed.")
        try:
            return cast(Any, kind)(**values)
        except InputError as exc:
            raise InputError(f"{path}.{exc.field}", str(exc)) from None
    if origin is tuple:
        if not isinstance(raw, list):
            raise InputError(path, "Supply a list.")
        return tuple(_decode(args[0], item, f"{path}.{i}", m2=m2) for i, item in enumerate(raw))
    if origin is Literal:
        if raw not in args or type(raw) is not type(args[0]):
            raise InputError(path, "Select one of the supported options.")
        return raw
    if kind is Decimal:
        if m2:
            if not isinstance(raw, str) or len(raw) > 65 or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw) is None:
                raise InputError(path, "Use a plain nonnegative decimal string with at most 64 digits.")
            if len(raw.replace(".", "")) > 64:
                raise InputError(path, "Use a plain nonnegative decimal string with at most 64 digits.")
            if not path.startswith("inputs.ani."):
                return Decimal(raw)
        try:
            return parse_percent(raw) if path.endswith("percent") else parse_gbp(raw)
        except InputError as exc:
            raise InputError(path, str(exc)) from None
    if kind is date:
        return parse_date(raw, field=path)
    if kind in (str, bool, int) and type(raw) is kind:
        if m2 and isinstance(raw, str):
            field_name = path.rsplit(".", 1)[-1]
            if field_name.isdecimal():
                field_name = path.rsplit(".", 2)[-2]
            if field_name.endswith(("_id", "_ids")) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", raw) is None:
                raise InputError(path, "Use an identifier of up to 128 letters, digits or . _ : - characters.")
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


def encode_m2_result(result: M2Result) -> dict[str, Any]:
    """Tag currency displays without labelling allocation quantities or rates as GBP."""
    return cast(dict[str, Any], _encode_m2(result))


def _encode_m2(value: Any, field: str = "") -> Any:
    if isinstance(value, Fraction):
        exact = {"numerator": str(value.numerator), "denominator": str(value.denominator)}
        if field == "gbp" or field.endswith("_gbp"):
            exact["display_gbp"] = display_gbp(value)
        return exact
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, AniResult):
        return value.to_wire()
    if is_dataclass(value) and not isinstance(value, type):
        encoded = {item.name: _encode_m2(getattr(value, item.name), item.name) for item in fields(value)}
        if isinstance(value, PayrollSettlement):
            for name in ("withheld_gbp", "repaid_gbp", "reported_owed_gbp", "reconciliation_difference_gbp"):
                encoded[name] = _encode_m2(getattr(value, name), name)
        return encoded
    if isinstance(value, tuple):
        return [_encode_m2(item, field) for item in value]
    return value
