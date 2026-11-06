"""Validated date and decimal inputs shared by the M1 domain."""


from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


ProblemStatus = Literal["input_error", "incomplete", "unsupported"]


@dataclass(frozen=True)
class Problem:
    status: ProblemStatus
    field: str
    message: str


class InputError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def parse_date(raw: object, *, field: str = "date") -> date:
    if isinstance(raw, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    raise InputError(field, "Enter a valid date as YYYY-MM-DD.")


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date:
            raise InputError("dates", "Use date-only period endpoints.")
        if self.start > self.end:
            raise InputError("end", "The end date must be on or after the start date.")

    def __contains__(self, day: date) -> bool:
        return self.start <= day <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def intersection(self, other: DateRange) -> DateRange | None:
        start, end = max(self.start, other.start), min(self.end, other.end)
        return DateRange(start, end) if start <= end else None


def _parse_nonnegative(raw: object, field: str, places: int) -> Decimal:
    if isinstance(raw, str) and re.fullmatch(rf"[0-9]+(?:\.[0-9]{{1,{places}}})?", raw):
        return Decimal(raw)
    raise InputError(field, f"Enter a nonnegative decimal with up to {places} fractional digits.")


def parse_gbp(raw: object) -> Decimal:
    return _parse_nonnegative(raw, "amount_gbp", 2)


def parse_percent(raw: object) -> Decimal:
    value = _parse_nonnegative(raw, "percent", 4)
    if value > 100:
        raise InputError("percent", "Enter a percentage from 0 to 100.")
    return value
