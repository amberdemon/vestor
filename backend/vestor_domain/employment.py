"""Gross salary and bonus evidence for the supported M1 tax year."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import groupby, pairwise
from typing import Literal

from .events import (
    DatedMoney, Disposition, ResultStatus, SourceStatus, _require_text, _source_status, resolve_events,
)
from .primitives import DateRange, InputError, Problem, validate_gbp
from .tax_year import TaxRules


PayBasis = Literal["before_reductions", "after_reductions", "unknown"]
ReceiptTiming = Literal["payment_date", "confirmed_receipt", "unconfirmed_entitlement", "unknown_date"]
PayKind = Literal["salary", "bonus"]
LineMethod = Literal["calendar_day_estimate", "unpaid", "dated_pay"]


@dataclass(frozen=True)
class SalaryPeriod:
    period_id: str
    dates: DateRange
    annual_gbp: Decimal | None
    source_status: SourceStatus
    source_note: str
    pay_frequency: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.period_id, "period_id")
        validate_gbp(self.annual_gbp, field="annual_gbp")
        _source_status(self.source_status)
        _require_text(self.source_note, "source_note")
        if self.pay_frequency is not None:
            _require_text(self.pay_frequency, "pay_frequency")


@dataclass(frozen=True)
class PayEvent:
    """Dated pay evidence.

    With payment_date, money.on is payment (including a payment on account).
    Omit entitlement_on only to confirm no earlier entitlement for actuals,
    or to use expected payment for forecasts with no known earlier entitlement.
    With confirmed_receipt, money.on is the established taxable date.
    With unknown_date, money.on is only a source reference date.
    """

    money: DatedMoney
    timing: ReceiptTiming
    basis: PayBasis
    entitlement_on: date | None = None

    def __post_init__(self) -> None:
        if self.timing not in ("payment_date", "confirmed_receipt", "unconfirmed_entitlement", "unknown_date"):
            raise InputError("timing", "Specify how the taxable receipt date was determined.")
        if self.basis not in ("before_reductions", "after_reductions", "unknown"):
            raise InputError("basis", "Specify whether pay is before or after payroll pension reductions.")
        if self.entitlement_on is not None and (
            type(self.entitlement_on) is not date or self.timing != "payment_date"
        ):
            raise InputError("entitlement_on", "Supply a date-only entitlement date alongside a payment date.")

    @property
    def receipt_on(self) -> date | None:
        # ITEPA 2003 s18, ordinary money earnings. See HMRC EIM42260.
        if self.timing in ("unknown_date", "unconfirmed_entitlement"):
            return None
        if self.entitlement_on is not None:
            return min(self.money.on, self.entitlement_on)
        return self.money.on


@dataclass(frozen=True)
class PayrollComponent:
    component_id: str
    kind: Literal["bonus", "rsu", "benefit"]
    amount_gbp: Decimal | None

    def __post_init__(self) -> None:
        _require_text(self.component_id, "component_id")
        if self.kind not in ("bonus", "rsu", "benefit"):
            raise InputError("kind", "Use bonus, rsu or benefit for an included payroll component.")
        validate_gbp(self.amount_gbp)


@dataclass(frozen=True)
class SalaryPayment:
    pay: PayEvent
    covered: DateRange
    replaces_period_ids: tuple[str, ...] = ()
    components: tuple[PayrollComponent, ...] | None = None

    def __post_init__(self) -> None:
        for period_id in self.replaces_period_ids:
            _require_text(period_id, "replaces_period_ids")
        if len(set(self.replaces_period_ids)) != len(self.replaces_period_ids):
            raise InputError("replaces_period_ids", "Link each covered salary period only once.")
        if self.components is not None:
            keys = {(part.kind, part.component_id) for part in self.components}
            if len(keys) != len(self.components):
                raise InputError("components", "List each included component only once per payment.")


@dataclass(frozen=True)
class EmploymentLine:
    kind: PayKind
    source: SalaryPeriod | SalaryPayment | PayEvent
    disposition: Disposition | Literal["unresolved"]
    method: LineMethod
    amount_gbp: Fraction | None = None
    covered: DateRange | None = None
    receipt_on: date | None = None
    replaced_by: str | None = None

    @property
    def basis(self) -> PayBasis:
        if isinstance(self.source, SalaryPeriod):
            return "before_reductions"
        if isinstance(self.source, SalaryPayment):
            return self.source.pay.basis
        return self.source.basis


@dataclass(frozen=True)
class EmploymentResult:
    status: ResultStatus
    rule_version: str
    tax_year: DateRange
    lines: tuple[EmploymentLine, ...]
    warnings: tuple[Problem, ...]

    def _gross(self, kind: PayKind) -> Fraction | None:
        if self.status not in ("confirmed", "estimated"):
            return None
        total = Fraction(0)
        for line in self.lines:
            if line.kind == kind and line.disposition == "included":
                if line.basis != "before_reductions" or line.amount_gbp is None:
                    return None
                total += line.amount_gbp
        return total

    @property
    def gross_salary_gbp(self) -> Fraction | None:
        return self._gross("salary")

    @property
    def gross_bonus_gbp(self) -> Fraction | None:
        return self._gross("bonus")


def _dated_salary_amount(
    payment: SalaryPayment, bonuses: dict[str, PayEvent], warnings: list[Problem],
) -> Fraction | None:
    pay = payment.pay
    if payment.components is None or any(part.amount_gbp is None for part in payment.components):
        warnings.append(Problem("incomplete", pay.money.event_id, "Confirm the included payroll components and GBP amounts."))
        return None
    included = Fraction(0)
    for part in payment.components:
        if part.kind == "bonus":
            bonus = bonuses.get(part.component_id)
            if bonus is None or (
                bonus.money.amount_gbp != part.amount_gbp
                or bonus.basis != pay.basis
                or bonus.money.source_status != pay.money.source_status
            ):
                warnings.append(Problem("incomplete", pay.money.event_id, "Reconcile the linked bonus amount, source and pay basis."))
                return None
        if part.amount_gbp is not None:
            included += Fraction(part.amount_gbp)
    if pay.money.amount_gbp is None:
        return None
    salary = Fraction(pay.money.amount_gbp) - included
    if salary < 0:
        warnings.append(Problem("input_error", pay.money.event_id, "Included components exceed the payroll total."))
        return None
    return salary


def _salary_rate_lines(
    periods: tuple[SalaryPeriod, ...],
    payments: tuple[SalaryPayment, ...],
    year: DateRange,
    warnings: list[Problem],
) -> list[EmploymentLine]:
    periods_by_id = {period.period_id: period for period in periods}
    if len(periods_by_id) != len(periods):
        warnings.append(Problem("input_error", "period_id", "Each salary period identifier must occur once."))
    if any(left.dates.intersection(right.dates) for left, right in pairwise(periods)):
        warnings.append(Problem("input_error", "salary_periods", "Salary rate periods cannot overlap."))
    if any(left.covered.intersection(right.covered) for left, right in pairwise(payments)):
        warnings.append(Problem("input_error", "salary_payments", "Salary payment coverage cannot overlap."))

    replaced_days: dict[int, str] = {}
    covered_days: set[int] = set()
    for payment in payments:
        event_id = payment.pay.money.event_id
        covered = year.intersection(payment.covered)
        if covered is not None:
            covered_days.update(range(covered.start.toordinal(), covered.end.toordinal() + 1))
        for period_id in payment.replaces_period_ids:
            period = periods_by_id.get(period_id)
            if period is None or not payment.covered.intersection(period.dates):
                warnings.append(Problem("input_error", event_id, "Link only supplied salary periods overlapping this payment."))
        for period in periods:
            overlap = payment.covered.intersection(period.dates)
            if overlap is None:
                continue
            if period.period_id not in payment.replaces_period_ids or period.annual_gbp == 0:
                if year.intersection(overlap) is not None:
                    warnings.append(Problem("incomplete", event_id, "Reconcile overlapping salary rate and payment coverage."))
                continue
            clipped = year.intersection(overlap)
            if clipped is not None:
                for day in range(clipped.start.toordinal(), clipped.end.toordinal() + 1):
                    replaced_days[day] = event_id

    lines: list[EmploymentLine] = []
    for period in periods:
        covered = year.intersection(period.dates)
        method: LineMethod = "unpaid" if period.annual_gbp == 0 else "calendar_day_estimate"
        if covered is None:
            lines.append(EmploymentLine("salary", period, "excluded", method))
            continue
        days = range(covered.start.toordinal(), covered.end.toordinal() + 1)
        covered_days.update(days)
        for replacement, segment in groupby(days, replaced_days.get):
            segment_days = list(segment)
            dates = DateRange(date.fromordinal(segment_days[0]), date.fromordinal(segment_days[-1]))
            if replacement is not None:
                lines.append(EmploymentLine("salary", period, "replaced", method, covered=dates, replaced_by=replacement))
                continue
            amount = None
            if period.annual_gbp is None or period.source_status == "unknown":
                warnings.append(Problem("incomplete", period.period_id, "Confirm the salary rate and its source."))
            else:
                amount = Fraction(period.annual_gbp) * dates.days / year.days
            lines.append(EmploymentLine("salary", period, "included", method, amount, dates))
    if len(covered_days) != year.days:
        warnings.append(Problem("incomplete", "salary_coverage", "Supply salary or explicit unpaid coverage for every day."))
    return lines


def calculate_employment(
    rules: TaxRules,
    *,
    salary_periods: Iterable[SalaryPeriod],
    salary_payments: Iterable[SalaryPayment],
    bonuses: Iterable[PayEvent],
    bonus_coverage_confirmed: bool,
) -> EmploymentResult:
    """Resolve dated earnings separately from salary service-day coverage."""
    year = rules.tax_year.dates
    periods = tuple(sorted(salary_periods, key=lambda period: (period.dates.start, period.period_id)))
    payments = tuple(sorted(salary_payments, key=lambda item: (item.covered.start, item.pay.money.event_id)))
    bonus_records = tuple(bonuses)
    dated = [*(item.pay for item in payments), *bonus_records]
    by_id = {pay.money.event_id: pay for pay in dated}
    payments_by_id = {item.pay.money.event_id: item for item in payments}
    warnings: list[Problem] = []
    if not bonus_coverage_confirmed:
        warnings.append(Problem("incomplete", "bonus_coverage", "Confirm that all bonuses or their absence are represented."))
    rate_links = {item.pay.money.event_id: item.replaces_period_ids for item in payments}
    for pay in dated:
        target = pay.money.replaces_forecast_id
        if target is None:
            continue
        payment = payments_by_id.get(pay.money.event_id)
        forecast = payments_by_id.get(target)
        if (payment is None) != (forecast is None) or (
            payment is not None and forecast is not None and payment.covered != forecast.covered
        ):
            warnings.append(Problem("input_error", pay.money.event_id, "Overrides must match pay type and dated salary coverage."))
        elif payment is not None and forecast is not None:
            rate_links[pay.money.event_id] = tuple(dict.fromkeys(
                (*payment.replaces_period_ids, *forecast.replaces_period_ids),
            ))

    resolved = resolve_events(
        (replace(pay.money, on=pay.receipt_on or pay.money.on) for pay in dated),
        rules,
        coverage_confirmed=True,
    )
    warnings.extend(resolved.warnings)
    active = {line.event_id for line in resolved.breakdown if line.disposition != "replaced"}
    active_payments = tuple(
        replace(item, replaces_period_ids=rate_links[item.pay.money.event_id])
        for item in payments if item.pay.money.event_id in active
    )
    lines = _salary_rate_lines(periods, active_payments, year, warnings)
    included_ids = {line.event_id for line in resolved.breakdown if line.disposition == "included"}
    active_bonuses = {pay.money.event_id: pay for pay in bonus_records if pay.money.event_id in active}
    linked_bonuses: set[str] = set()
    for line in resolved.breakdown:
        pay = by_id[line.event_id]
        payment = payments_by_id.get(line.event_id)
        receipt = pay.receipt_on
        amount = None
        disposition: Disposition | Literal["unresolved"] = line.disposition
        if disposition != "replaced" and receipt is None and (
            pay.timing == "unknown_date" or pay.money.on >= year.start
        ):
            disposition = "unresolved"
            warnings.append(Problem("incomplete", line.event_id, "Confirm when earnings were first paid or payable."))
        included_bonus = False
        if payment is not None and disposition != "replaced":
            if disposition == "excluded" and pay.money.source_status == "unknown" and year.intersection(payment.covered):
                warnings.append(Problem("incomplete", line.event_id, "Confirm the source of the dated salary coverage."))
            for part in payment.components or ():
                if part.kind == "bonus":
                    if part.component_id in linked_bonuses:
                        warnings.append(Problem("incomplete", part.component_id, "Reconcile a bonus linked to multiple salary payments."))
                    linked_bonuses.add(part.component_id)
                    included_bonus |= part.component_id in included_ids
            if included_bonus and disposition == "excluded":
                _dated_salary_amount(payment, active_bonuses, warnings)
        if disposition == "included":
            if pay.basis == "unknown":
                warnings.append(Problem("incomplete", line.event_id, "Confirm the payroll pension reduction basis."))
            elif pay.money.amount_gbp is not None and pay.money.source_status != "unknown":
                amount = (
                    Fraction(pay.money.amount_gbp) if payment is None
                    else _dated_salary_amount(payment, active_bonuses, warnings)
                )
        lines.append(EmploymentLine(
            "bonus" if payment is None else "salary", pay if payment is None else payment,
            disposition, "dated_pay", amount, None if payment is None else payment.covered,
            receipt, line.replaced_by,
        ))

    estimated_salary_coverage = any(
        item.pay.money.source_status == "forecast" and year.intersection(item.covered)
        for item in active_payments
    )
    estimated = resolved.status == "estimated" or estimated_salary_coverage or any(
        line.disposition == "included" and (
            line.method == "calendar_day_estimate"
            or isinstance(line.source, SalaryPeriod) and line.source.source_status == "forecast"
        )
        for line in lines
    )
    status: ResultStatus = "confirmed"
    if any(warning.status == "input_error" for warning in warnings):
        status = "input_error"
    elif warnings:
        status = "incomplete"
    elif estimated:
        status = "estimated"
    return EmploymentResult(status, rules.version, year, tuple(lines), tuple(warnings))
