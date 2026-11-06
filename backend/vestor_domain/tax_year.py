"""UK tax-year dates and the single verified M1 ruleset."""


from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .primitives import DateRange, InputError, Problem


@dataclass(frozen=True)
class TaxYear:
    start_year: int

    def __post_init__(self) -> None:
        if type(self.start_year) is not int or not 1 <= self.start_year < date.max.year:
            raise InputError("start_year", "Enter a valid four-digit tax-year start year.")

    @property
    def dates(self) -> DateRange:
        return DateRange(date(self.start_year, 4, 6), date(self.start_year + 1, 4, 5))

    @classmethod
    def for_date(cls, day: date) -> TaxYear:
        if type(day) is not date:
            raise InputError("date", "Use a date-only value.")
        return cls(day.year if (day.month, day.day) >= (4, 6) else day.year - 1)


@dataclass(frozen=True)
class TaxRules:
    tax_year: TaxYear
    jurisdictions: tuple[str, ...]
    version: str
    source_url: str
    verified_on: date
    standard_allowance_gbp: Decimal
    taper_threshold_gbp: Decimal
    taper_reduction_per_pound: Decimal
    allowance_floor_gbp: Decimal


_RULES = TaxRules(
    tax_year=TaxYear(2026),
    jurisdictions=("england", "northern_ireland"),
    version="uk-eng-ni-2026-27-v1",
    source_url=(
        "https://www.gov.uk/government/publications/rates-and-allowances-income-tax/"
        "income-tax-rates-and-allowances-current-and-past"
    ),
    verified_on=date(2026, 11, 6),
    standard_allowance_gbp=Decimal("12570"),
    taper_threshold_gbp=Decimal("100000"),
    taper_reduction_per_pound=Decimal("0.5"),
    allowance_floor_gbp=Decimal("0"),
)


def select_tax_rules(
    start_year: int | None,
    jurisdiction: str | None,
    *,
    standard_treatment: bool | None,
) -> TaxRules | Problem:
    """Select rules for full-year UK residence and standard allowance treatment."""
    if start_year is not None:
        try:
            TaxYear(start_year)
        except InputError as error:
            return Problem("input_error", error.field, str(error))
    if jurisdiction is not None and jurisdiction not in ("england", "northern_ireland", "scotland", "wales"):
        return Problem("input_error", "jurisdiction", "Select a UK income-tax jurisdiction.")
    if standard_treatment is not None and type(standard_treatment) is not bool:
        return Problem("input_error", "standard_treatment", "Specify whether standard treatment applies.")

    if start_year is not None and start_year != _RULES.tax_year.start_year:
        return Problem("unsupported", "start_year", "Only 2026/27 has verified rules.")
    if jurisdiction is not None and jurisdiction not in _RULES.jurisdictions:
        return Problem("unsupported", "jurisdiction", "Only England and Northern Ireland rules are supported.")
    if standard_treatment is False:
        return Problem("unsupported", "standard_treatment", "Full-year UK residence and standard allowance treatment are required.")
    if start_year is None:
        return Problem("incomplete", "start_year", "Select a tax year.")
    if jurisdiction is None:
        return Problem("incomplete", "jurisdiction", "Select an income-tax jurisdiction.")
    if standard_treatment is None:
        return Problem("incomplete", "standard_treatment", "Confirm residence and standard allowance treatment.")
    return _RULES
