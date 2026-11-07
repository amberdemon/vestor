"""Effective-dated benefit evidence and payroll reconciliation for M1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import combinations, groupby
from typing import Literal

from .employment import EmploymentResult, SalaryPayment
from .events import Disposition, ResultStatus, SourceStatus, _require_text, _source_status
from .primitives import DateRange, InputError, Problem, validate_gbp
from .tax_year import TaxRules


BenefitBasis = Literal["annual_taxable", "payrolled", "p11d"]
Taxability = Literal["yes", "no", "unknown"]


@dataclass(frozen=True)
class BenefitPeriod:
    period_id: str
    benefit_id: str
    category: str
    dates: DateRange
    taxability: Taxability
    source_status: SourceStatus
    source_note: str
    basis: BenefitBasis | None = None
    taxable_gbp: Decimal | None = None
    annual_premium_gbp: Decimal | None = None
    payer: str | None = None
    employee_contribution_gbp: Decimal | None = None
    daily_apportionment_confirmed: bool = False
    included_in_payroll: bool | None = None
    payroll_ids: tuple[str, ...] = ()
    replaces_forecast_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.period_id, "period_id")
        _require_text(self.benefit_id, "benefit_id")
        _require_text(self.category, "category")
        _source_status(self.source_status)
        _require_text(self.source_note, "source_note")
        if self.taxability not in ("yes", "no", "unknown"):
            raise InputError("taxability", "Use yes, no or unknown.")
        if self.basis not in (None, "annual_taxable", "payrolled", "p11d"):
            raise InputError("basis", "Use annual taxable value, payroll or P11D evidence.")
        validate_gbp(self.taxable_gbp, field="taxable_gbp")
        validate_gbp(self.annual_premium_gbp, field="annual_premium_gbp")
        validate_gbp(self.employee_contribution_gbp, field="employee_contribution_gbp")
        if self.payer is not None:
            _require_text(self.payer, "payer")
        if type(self.daily_apportionment_confirmed) is not bool:
            raise InputError("daily_apportionment_confirmed", "Confirm daily apportionment with true or false.")
        if self.included_in_payroll is not None and type(self.included_in_payroll) is not bool:
            raise InputError("included_in_payroll", "Use true, false or null for payroll inclusion.")
        for field, ids in (("payroll_ids", self.payroll_ids), ("replaces_forecast_ids", self.replaces_forecast_ids)):
            for value in ids:
                _require_text(value, field)
            if len(set(ids)) != len(ids):
                raise InputError(field, "Link each record only once.")


@dataclass(frozen=True)
class BenefitLine:
    source: BenefitPeriod
    disposition: Disposition | Literal["unresolved"]
    explanation: str
    covered: DateRange | None = None
    period_fraction: Fraction | None = None
    amount_gbp: Fraction | None = None
    replaced_by: str | None = None


@dataclass(frozen=True)
class BenefitResult:
    status: ResultStatus
    rule_version: str
    tax_year: DateRange
    employment: EmploymentResult
    lines: tuple[BenefitLine, ...]
    warnings: tuple[Problem, ...]

    @property
    def taxable_gbp(self) -> Fraction | None:
        """Full benefit subtotal, to combine with isolated salary and bonus."""
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum((line.amount_gbp for line in self.lines if line.amount_gbp is not None), Fraction(0))

    @property
    def included_in_payroll_gbp(self) -> Fraction | None:
        """Portion of the full benefit subtotal already in raw payroll evidence."""
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum((
            line.amount_gbp for line in self.lines
            if line.amount_gbp is not None and line.source.included_in_payroll
        ), Fraction(0))


def _replacements(
    sources: tuple[BenefitPeriod, ...], year: DateRange, warnings: list[Problem],
) -> dict[str, dict[int, str]]:
    by_id = {record.period_id: record for record in sources}
    if len(by_id) != len(sources):
        warnings.append(Problem("input_error", "period_id", "Each benefit period identifier must occur once."))

    linked: set[tuple[str, str]] = set()
    replacements: dict[str, dict[int, str]] = defaultdict(dict)
    for actual in sources:
        for forecast_id in actual.replaces_forecast_ids:
            forecast = by_id.get(forecast_id)
            overlap = None if forecast is None else actual.dates.intersection(forecast.dates)
            if (
                actual.source_status != "actual" or forecast is None or overlap is None
                or forecast.source_status != "forecast" or forecast.benefit_id != actual.benefit_id
            ):
                warnings.append(Problem(
                    "input_error", actual.period_id, "Link only overlapping forecasts for this benefit to the actual.",
                ))
                continue
            linked.add((forecast_id, actual.period_id))
            if year.intersection(actual.dates) != actual.dates or actual.taxability == "unknown":
                continue
            if actual.taxability == "yes" and (
                actual.taxable_gbp is None or actual.basis not in ("payrolled", "p11d")
            ):
                continue
            if actual.taxability == "no" and (
                actual.taxable_gbp not in (None, 0) or actual.included_in_payroll or actual.payroll_ids
            ):
                continue
            for day in range(overlap.start.toordinal(), overlap.end.toordinal() + 1):
                replacements[forecast_id][day] = actual.period_id

    by_benefit = groupby(sources, key=lambda record: record.benefit_id)
    for benefit_id, periods in by_benefit:
        for left, right in combinations(periods, 2):
            if left.dates.intersection(right.dates) and (
                (left.period_id, right.period_id) not in linked and (right.period_id, left.period_id) not in linked
            ):
                warnings.append(Problem(
                    "input_error", benefit_id, "Overlapping periods for this benefit require an explicit actual override.",
                ))
    return replacements


def _value_line(
    record: BenefitPeriod, covered: DateRange, year: DateRange, warnings: list[Problem],
) -> BenefitLine:
    if record.source_status == "unknown" or record.taxability == "unknown":
        reason = "Confirm the benefit's source and whether it is taxable or exempt."
    elif record.taxability == "no":
        if record.taxable_gbp in (None, 0) and not record.included_in_payroll and not record.payroll_ids:
            return BenefitLine(record, "excluded", "Benefit declared non-taxable.", covered)
        reason = "Reconcile the declared exemption with the taxable amount or payroll evidence."
    elif record.taxable_gbp is None:
        reason = "Supply the taxable value after applicable adjustments."
    elif record.source_status == "actual" and record.basis in ("payrolled", "p11d"):
        if covered == record.dates:
            return BenefitLine(
                record, "included", "Confirmed taxable value for the stated coverage.",
                covered, amount_gbp=Fraction(record.taxable_gbp),
            )
        reason = "Supply a confirmed taxable amount with coverage wholly in the selected tax year."
    elif record.source_status == "forecast" and record.basis == "annual_taxable":
        if record.daily_apportionment_confirmed:
            fraction = Fraction(covered.days, year.days)
            return BenefitLine(
                record, "included", "Annual taxable value apportioned by calendar days.",
                covered, fraction, Fraction(record.taxable_gbp) * fraction,
            )
        reason = "Confirm that calendar-day apportionment suits the benefit's valuation."
    else:
        reason = "Confirm an annual forecast taxable value or a payroll/P11D actual."
    warnings.append(Problem("incomplete", record.period_id, reason))
    return BenefitLine(record, "unresolved", reason, covered)


def _reconcile_payroll(
    lines: list[BenefitLine], employment: EmploymentResult, warnings: list[Problem],
) -> None:
    components: dict[str, dict[str, Fraction]] = defaultdict(dict)
    sources: dict[str, SourceStatus] = {}
    outside_year: set[str] = set()
    for pay_line in employment.lines:
        payment = pay_line.source
        if not isinstance(payment, SalaryPayment) or pay_line.disposition == "replaced":
            continue
        if pay_line.disposition == "excluded":
            outside_year.update(part.component_id for part in payment.components or () if part.kind == "benefit")
            continue
        payment_id = payment.pay.money.event_id
        if pay_line.disposition == "unresolved" or pay_line.amount_gbp is None or payment.components is None:
            warnings.append(Problem("incomplete", payment_id, "Confirm the relevant taxable payroll and its composition."))
            continue
        sources[payment_id] = payment.pay.money.source_status
        for part in payment.components:
            if part.kind == "benefit" and part.amount_gbp is not None:
                components[part.component_id][payment_id] = Fraction(part.amount_gbp)

    amounts: dict[str, Fraction] = defaultdict(Fraction)
    records: dict[str, BenefitPeriod] = {}
    for line in lines:
        if line.disposition == "included" and line.amount_gbp is not None:
            key = line.source.period_id
            amounts[key] += line.amount_gbp
            records[key] = line.source
    for key, record in records.items():
        matched = components.pop(key, {})
        if key in outside_year:
            warnings.append(Problem("incomplete", key, "Reconcile in-year benefit evidence with payroll outside the tax year."))
            continue
        if record.included_in_payroll is False and not matched and not record.payroll_ids:
            continue
        if (
            record.included_in_payroll is True and record.basis != "p11d" and matched
            and matched.keys() == set(record.payroll_ids)
            and sum(matched.values(), Fraction(0)) == amounts[key]
            and all(sources[payment_id] == record.source_status for payment_id in matched)
        ):
            continue
        warnings.append(Problem("incomplete", key, "Reconcile the benefit's inclusion, source and value with named payroll components."))
    for key in components:
        warnings.append(Problem("incomplete", key, "Supply matching evidence for the benefit included in taxable payroll."))


def calculate_benefits(
    rules: TaxRules,
    *,
    benefits: Iterable[BenefitPeriod],
    employment: EmploymentResult,
    coverage_confirmed: bool,
) -> BenefitResult:
    """Clip forecasts to the tax year and reconcile actual amounts with payroll."""
    year = rules.tax_year.dates
    sources = tuple(sorted(benefits, key=lambda record: (record.benefit_id, record.dates.start, record.period_id)))
    warnings: list[Problem] = []
    if not coverage_confirmed:
        warnings.append(Problem("incomplete", "benefit_coverage", "Confirm all benefits or their absence."))
    if employment.rule_version != rules.version or employment.tax_year != year:
        warnings.append(Problem("input_error", "employment", "Employment must use the selected tax year and rules."))
    replacements = _replacements(sources, year, warnings)
    lines: list[BenefitLine] = []
    for record in sources:
        covered = year.intersection(record.dates)
        if covered is None:
            lines.append(BenefitLine(record, "excluded", "Outside the selected tax year."))
            continue
        days = range(covered.start.toordinal(), covered.end.toordinal() + 1)
        for replacement, segment in groupby(days, replacements.get(record.period_id, {}).get):
            segment_days = list(segment)
            dates = DateRange(date.fromordinal(segment_days[0]), date.fromordinal(segment_days[-1]))
            if replacement is not None:
                lines.append(BenefitLine(record, "replaced", "Covered by confirmed actual evidence.", dates, replaced_by=replacement))
            else:
                lines.append(_value_line(record, dates, year, warnings))

    _reconcile_payroll(lines, employment, warnings)
    status: ResultStatus = "confirmed"
    if any(warning.status == "input_error" for warning in warnings):
        status = "input_error"
    elif warnings:
        status = "incomplete"
    elif any(line.covered is not None and line.disposition != "replaced" and line.source.source_status == "forecast" for line in lines):
        status = "estimated"
    return BenefitResult(status, rules.version, year, employment, tuple(lines), tuple(warnings))
