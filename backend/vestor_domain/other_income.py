"""Supported manually determined GBP other income; no tax-bill calculation."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from fractions import Fraction
from itertools import combinations
from typing import Literal

from .events import DatedMoney, Disposition, ResultStatus, _require_text, resolve_events
from .primitives import DateRange, InputError, Problem
from .tax_year import TaxRules


@dataclass(frozen=True)
class OtherIncome:
    money: DatedMoney
    category: Literal["interest", "dividends", "uk_trading", "uk_property", "other"]
    basis: Literal["dated", "tax_year"]
    coverage_ids: tuple[str, ...]
    treatment: Literal["taxable", "exempt", "unknown"]
    treatment_confirmed: bool | None
    allocation_confirmed: bool
    assessment_year: int | None = None
    exemption_reason: str | None = None

    def __post_init__(self) -> None:
        if self.category not in ("interest", "dividends", "uk_trading", "uk_property", "other"):
            raise InputError("category", "Select a supported category or explicitly declare other income.")
        if self.basis not in ("dated", "tax_year"):
            raise InputError("basis", "Use a dated receipt or a total for a stated assessment tax year.")
        if self.treatment not in ("taxable", "exempt", "unknown"):
            raise InputError("treatment", "Specify taxable, exempt or unknown treatment.")
        if self.treatment_confirmed is not None and type(self.treatment_confirmed) is not bool:
            raise InputError("treatment_confirmed", "Use true, false or null for supported treatment confirmation.")
        if type(self.allocation_confirmed) is not bool:
            raise InputError("allocation_confirmed", "Confirm the taxable receipt date or assessment year.")
        if self.basis == "tax_year":
            if type(self.assessment_year) is not int or not 1 <= self.assessment_year <= 9998:
                raise InputError("assessment_year", "Supply the starting year of the assessment tax year.")
        elif self.assessment_year is not None:
            raise InputError("assessment_year", "Dated receipts use their taxable receipt date, not an assessment-year override.")
        if self.category in ("uk_trading", "uk_property") and self.basis != "tax_year":
            raise InputError("basis", "Supply manually determined taxable profits for a stated assessment tax year.")
        if not isinstance(self.coverage_ids, tuple) or not self.coverage_ids:
            raise InputError("coverage_ids", "Identify the income streams covered, including every component of a consolidated total.")
        for key in self.coverage_ids:
            _require_text(key, "coverage_ids")
        if len(set(self.coverage_ids)) != len(self.coverage_ids):
            raise InputError("coverage_ids", "Identify each underlying income stream once.")
        if self.treatment == "exempt":
            _require_text(self.exemption_reason, "exemption_reason")
        elif self.exemption_reason is not None:
            raise InputError("exemption_reason", "Only exempt income can have an exemption reason.")

    @property
    def allocated_dates(self) -> DateRange:
        if self.assessment_year is not None:
            return DateRange(date(self.assessment_year, 4, 6), date(self.assessment_year + 1, 4, 5))
        return DateRange(self.money.on, self.money.on)


@dataclass(frozen=True)
class OtherIncomeLine:
    source: OtherIncome
    disposition: Disposition | Literal["unresolved"]
    explanation: str
    amount_gbp: Fraction | None = None
    replaced_by: str | None = None


@dataclass(frozen=True)
class OtherIncomeResult:
    status: ResultStatus
    rule_version: str
    tax_year: DateRange
    lines: tuple[OtherIncomeLine, ...]
    warnings: tuple[Problem, ...]

    @property
    def taxable_gbp(self) -> Fraction | None:
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum((line.amount_gbp for line in self.lines if line.amount_gbp is not None), Fraction(0))


def calculate_other_income(
    rules: TaxRules, *, entries: Iterable[OtherIncome], coverage_confirmed: bool,
) -> OtherIncomeResult:
    """Resolve supported income only; qualifying adjustments remain in pensions.

    2026/27, reviewed 8 November 2026: HMRC adjusted-net-income guidance
    https://www.gov.uk/guidance/adjusted-net-income includes savings interest,
    dividends and taxable profits before personal allowances. Savings/dividend
    nil-rate allowances are not exemptions. Explicit ISA exemptions are separate:
    https://www.gov.uk/apply-tax-free-interest-on-savings
    Manual profits already reflect applicable accounting/allowance rules; this
    module cannot determine them, offset losses or calculate tax.
    """
    records = tuple(entries)
    by_id = {item.money.event_id: item for item in records}
    # For annual totals the evidence date is retained on the source record;
    # only the assessment year controls allocation. Never annualise a receipt.
    resolved = resolve_events(
        (replace(item.money, on=item.allocated_dates.start) for item in records),
        rules, coverage_confirmed=coverage_confirmed,
    )
    warnings = list(resolved.warnings)
    for item in records:
        target = by_id.get(item.money.replaces_forecast_id or "")
        if target is not None and (
            target.category != item.category or target.basis != item.basis
            or set(target.coverage_ids) != set(item.coverage_ids)
        ):
            warnings.append(Problem("input_error", item.money.event_id,
                                    "Replace evidence for the same income category, allocation basis and underlying streams."))

    active = [by_id[line.event_id] for line in resolved.breakdown if line.disposition != "replaced"]
    for left, right in combinations(active, 2):
        if set(left.coverage_ids).intersection(right.coverage_ids) and left.allocated_dates.intersection(right.allocated_dates):
            warnings.append(Problem("input_error", right.money.event_id,
                                    "Reconcile overlapping income streams; a consolidated total cannot accompany its components."))

    lines: list[OtherIncomeLine] = []
    for evidence in resolved.breakdown:
        item = by_id[evidence.event_id]
        disposition: Disposition | Literal["unresolved"] = evidence.disposition
        amount = None
        explanation = "Outside the selected assessment tax year or taxable receipt dates."
        if disposition == "replaced":
            explanation = "Superseded by explicitly linked actual income evidence."
        elif not item.allocation_confirmed:
            disposition = "unresolved"
            explanation = "Confirm the taxable receipt date or assessment year; the reference date cannot establish allocation."
            warnings.append(Problem("incomplete", evidence.event_id, explanation))
        if disposition == "included":
            if item.category == "other" or item.treatment_confirmed is False:
                explanation = "This income requires treatment outside the supported UK categories."
                warnings.append(Problem("unsupported", evidence.event_id, explanation))
            elif item.treatment == "unknown" or item.treatment_confirmed is None:
                explanation = "Confirm supported taxable treatment or an actual exemption; a nil-rate allowance is not an exemption."
                warnings.append(Problem("incomplete", evidence.event_id, explanation))
            elif item.money.amount_gbp is None or item.money.source_status == "unknown":
                explanation = "Confirm the GBP amount and source status."
            elif item.treatment == "exempt":
                disposition = "excluded"
                amount = Fraction(0)
                explanation = f"Excluded tax-exempt income: {item.exemption_reason}."
            else:
                amount = Fraction(item.money.amount_gbp)
                explanation = (
                    "Gross taxable income before savings/dividend nil-rate allowances."
                    if item.category in ("interest", "dividends") else
                    "Manually determined nonnegative UK taxable profit for the stated assessment year; no accounting or loss relief calculated."
                )
        lines.append(OtherIncomeLine(item, disposition, explanation, amount, evidence.replaced_by))

    status: ResultStatus = resolved.status
    for blocking in ("incomplete", "unsupported", "input_error"):
        if any(warning.status == blocking for warning in warnings):
            status = blocking
    return OtherIncomeResult(status, rules.version, rules.tax_year.dates, tuple(lines), tuple(warnings))
