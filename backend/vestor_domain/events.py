"""Dated GBP evidence and deterministic resolution of explicit actual overrides."""


from __future__ import annotations
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from .primitives import InputError, Problem, ProblemStatus, parse_date, parse_gbp, validate_gbp
from .tax_year import TaxRules


SourceStatus = Literal["actual", "forecast", "unknown"]
Disposition = Literal["included", "excluded", "replaced"]
ResultStatus = Literal["confirmed", "estimated"] | ProblemStatus


def _require_text(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise InputError(field, "Enter nonblank text.")
    return raw


def _source_status(raw: object) -> SourceStatus:
    if raw == "actual":
        return "actual"
    if raw == "forecast":
        return "forecast"
    if raw == "unknown":
        return "unknown"
    raise InputError("source_status", "Use actual, forecast or unknown.")


@dataclass(frozen=True)
class DatedMoney:
    event_id: str
    on: date
    amount_gbp: Decimal | None
    source_status: SourceStatus
    source_note: str
    replaces_forecast_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        if type(self.on) is not date:
            raise InputError("on", "Use a date-only value.")

        validate_gbp(self.amount_gbp)
        _source_status(self.source_status)
        _require_text(self.source_note, "source_note")
        if self.replaces_forecast_id is not None:
            _require_text(self.replaces_forecast_id, "replaces_forecast_id")
            if self.source_status != "actual" or self.replaces_forecast_id == self.event_id:
                raise InputError("replaces_forecast_id", "Only an actual can replace a different forecast event.")

    @classmethod
    def from_wire(cls, raw: Mapping[str, object]) -> DatedMoney:
        if "amount_gbp" not in raw:
            raise InputError("amount_gbp", "Supply a GBP amount or explicitly mark it unknown with null.")
        amount = raw["amount_gbp"]
        replacement = raw.get("replaces_forecast_id")
        return cls(
            event_id=_require_text(raw.get("event_id"), "event_id"),
            on=parse_date(raw.get("on"), field="on"),
            amount_gbp=None if amount is None else parse_gbp(amount),
            source_status=_source_status(raw.get("source_status")),
            source_note=_require_text(raw.get("source_note"), "source_note"),
            replaces_forecast_id=None if replacement is None else _require_text(replacement, "replaces_forecast_id"),
        )

    def to_wire(self) -> dict[str, str | None]:
        return {
            "event_id": self.event_id,
            "on": self.on.isoformat(),
            "amount_gbp": None if self.amount_gbp is None else format(self.amount_gbp, "f"),
            "source_status": self.source_status,
            "source_note": self.source_note,
            "replaces_forecast_id": self.replaces_forecast_id,
        }


@dataclass(frozen=True)
class BreakdownLine:
    event_id: str
    disposition: Disposition
    replaced_by: str | None = None


@dataclass(frozen=True)
class EventResult:
    status: ResultStatus
    source_events: tuple[DatedMoney, ...]
    rule_version: str
    breakdown: tuple[BreakdownLine, ...] = ()
    warnings: tuple[Problem, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status,
            "value": None,
            "source_events": [event.to_wire() for event in self.source_events],
            "rule_version": self.rule_version,
            "breakdown": [asdict(line) for line in self.breakdown],
            "warnings": [asdict(warning) for warning in self.warnings],
        }


def resolve_events(
    events: Iterable[DatedMoney], rules: TaxRules, *, coverage_confirmed: bool,
) -> EventResult:
    """Select dated records in the verified year, preserving every source event."""
    sources = tuple(sorted(events, key=lambda event: (event.on, event.event_id)))
    by_id = {event.event_id: event for event in sources}
    if len(by_id) != len(sources):
        warning = Problem("input_error", "event_id", "Each event identifier must occur once.")
        return EventResult("input_error", (), rules.version, warnings=(warning,))

    replacements: dict[str, str] = {}
    for event in sources:
        forecast_id = event.replaces_forecast_id
        if forecast_id is None:
            continue
        forecast = by_id.get(forecast_id)
        if forecast is None or forecast.source_status != "forecast" or forecast_id in replacements:
            warning = Problem("input_error", "replaces_forecast_id", "Each override must link to a unique supplied forecast.")
            return EventResult("input_error", sources, rules.version, warnings=(warning,))
        replacements[forecast_id] = event.event_id

    dates = rules.tax_year.dates
    breakdown = []
    warnings = []
    estimated = False
    if not coverage_confirmed:
        warnings.append(Problem("incomplete", "coverage", "Confirm coverage of the selected event set."))
    for event in sources:
        replacement = replacements.get(event.event_id)
        if replacement is not None:
            breakdown.append(BreakdownLine(event.event_id, "replaced", replacement))
        elif event.on not in dates:
            breakdown.append(BreakdownLine(event.event_id, "excluded"))
        else:
            breakdown.append(BreakdownLine(event.event_id, "included"))
            if event.amount_gbp is None or event.source_status == "unknown":
                warnings.append(Problem("incomplete", event.event_id, "Confirm the GBP amount and its source status."))
            estimated |= event.source_status == "forecast"

    status: ResultStatus = "incomplete" if warnings else "estimated" if estimated else "confirmed"
    return EventResult(status, sources, rules.version, tuple(breakdown), tuple(warnings))
