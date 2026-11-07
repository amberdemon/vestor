"""Manual gross GBP RSU employment income; no FX, disposals or cash calculation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from datetime import date
from fractions import Fraction
from typing import Literal

from .employment import EmploymentResult, SalaryPayment
from .events import DatedMoney, Disposition, ResultStatus, SourceStatus, _require_text, resolve_events
from .primitives import DateRange, InputError, Problem, ProblemStatus, parse_percent
from .tax_year import TaxRules


@dataclass(frozen=True)
class RsuEvent:
    money: DatedMoney
    charge_date_confirmed: bool
    supported_award: bool | None
    included_in_payroll: bool | None = None
    payroll_ids: tuple[str, ...] = ()
    label: str | None = None
    sold_to_cover_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.charge_date_confirmed) is not bool:
            raise InputError("charge_date_confirmed", "Confirm the taxable charge date with true or false.")
        for field, value in (("supported_award", self.supported_award), ("included_in_payroll", self.included_in_payroll)):
            if value is not None and type(value) is not bool:
                raise InputError(field, "Use true, false or null.")
        for key in self.payroll_ids:
            _require_text(key, "payroll_ids")
        if len(set(self.payroll_ids)) != len(self.payroll_ids):
            raise InputError("payroll_ids", "Link each payroll record only once.")
        if self.label is not None:
            _require_text(self.label, "label")
        percent = self.sold_to_cover_percent
        if percent is not None:
            if not isinstance(percent, Decimal):
                raise InputError("sold_to_cover_percent", "Use an exact Decimal percentage.")
            parse_percent(str(percent))


@dataclass(frozen=True)
class RsuLine:
    source: RsuEvent
    disposition: Disposition | Literal["unresolved"]
    explanation: str
    amount_gbp: Fraction | None = None
    replaced_by: str | None = None


@dataclass(frozen=True)
class RsuResult:
    status: ResultStatus
    rule_version: str
    tax_year: DateRange
    employment: EmploymentResult
    lines: tuple[RsuLine, ...]
    warnings: tuple[Problem, ...]

    @property
    def taxable_gbp(self) -> Fraction | None:
        """Full gross RSU income, to combine with isolated salary and bonus."""
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum((line.amount_gbp for line in self.lines if line.amount_gbp is not None), Fraction(0))

    @property
    def included_in_payroll_gbp(self) -> Fraction | None:
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum((line.amount_gbp for line in self.lines
                    if line.amount_gbp is not None and line.source.included_in_payroll), Fraction(0))


def _reconcile_payroll(lines: list[RsuLine], employment: EmploymentResult, warnings: list[Problem]) -> None:
    components: dict[str, dict[str, Fraction]] = defaultdict(dict)
    sources: dict[str, SourceStatus] = {}
    payroll_dates: dict[str, date] = {}
    outside_year: set[str] = set()
    for pay_line in employment.lines:
        payment = pay_line.source
        if not isinstance(payment, SalaryPayment) or pay_line.disposition == "replaced":
            continue
        if pay_line.disposition == "excluded":
            outside_year.update(part.component_id for part in payment.components or () if part.kind == "rsu")
            continue
        key = payment.pay.money.event_id
        if pay_line.disposition == "unresolved" or pay_line.amount_gbp is None or payment.components is None:
            warnings.append(Problem("incomplete", key, "Confirm the relevant taxable payroll and its composition."))
            continue
        sources[key] = payment.pay.money.source_status
        if pay_line.receipt_on is not None:
            payroll_dates[key] = pay_line.receipt_on
        for part in payment.components:
            if part.kind == "rsu" and part.amount_gbp is not None:
                components[part.component_id][key] = Fraction(part.amount_gbp)

    for line in lines:
        if line.disposition != "included" or line.amount_gbp is None:
            continue
        record = line.source
        key = record.money.event_id
        matched = components.pop(key, {})
        if key in outside_year:
            warnings.append(Problem("incomplete", key, "Reconcile in-year vest income with payroll outside the tax year."))
        elif record.included_in_payroll is False and not matched and not record.payroll_ids:
            continue
        elif (
            record.included_in_payroll is True and matched
            and matched.keys() == set(record.payroll_ids)
            and sum(matched.values(), Fraction(0)) == line.amount_gbp
            and all(sources[payment_id] == record.money.source_status for payment_id in matched)
            and all(payment_id in payroll_dates and payroll_dates[payment_id] >= record.money.on for payment_id in matched)
        ):
            continue
        else:
            warnings.append(Problem("incomplete", key, "Reconcile the vest's inclusion, source and gross GBP value with named payroll components."))
    for key in components:
        warnings.append(Problem("incomplete", key, "Supply matching vest evidence for the RSU included in taxable payroll."))


def calculate_rsu_income(
    rules: TaxRules,
    *,
    events: Iterable[RsuEvent],
    employment: EmploymentResult,
    coverage_confirmed: bool,
) -> RsuResult:
    """Resolve explicit actual replacements before date filtering, preserving evidence.

    Ordinary awards only: HMRC ERSM20194 example 1 (reviewed 7 November
    2026), for 2026/27. Scheme facts and the charge date must be confirmed.
    The supplied amount is gross taxable GBP, irrespective of shares retained.
    """
    records = tuple(events)
    resolved = resolve_events((record.money for record in records), rules, coverage_confirmed=coverage_confirmed)
    by_id = {record.money.event_id: record for record in records}
    warnings = list(resolved.warnings)
    if employment.rule_version != rules.version or employment.tax_year != rules.tax_year.dates:
        warnings.append(Problem("input_error", "employment", "Employment must use the selected tax year and rules."))
    lines: list[RsuLine] = []
    for line in resolved.breakdown:
        record = by_id[line.event_id]
        disposition: Disposition | Literal["unresolved"] = line.disposition
        amount = None
        explanation = "Outside the selected tax year."
        if disposition == "replaced":
            explanation = "Superseded by explicitly linked actual GBP evidence."
        elif record.supported_award is False and (disposition == "included" or not record.charge_date_confirmed):
            explanation = "This award requires a tax treatment outside the supported ordinary vest scope."
            warnings.append(Problem("unsupported", line.event_id, explanation))
        elif not record.charge_date_confirmed:
            disposition = "unresolved"
            explanation = "Confirm the taxable charge date; the supplied reference date cannot determine the tax year."
            warnings.append(Problem("incomplete", line.event_id, explanation))
        elif disposition == "included":
            if record.supported_award is None:
                explanation = "Confirm that this is an ordinary supported RSU vest award."
                warnings.append(Problem("incomplete", line.event_id, explanation))
            elif record.money.amount_gbp is not None and record.money.source_status != "unknown":
                amount = Fraction(record.money.amount_gbp)
                explanation = "Gross taxable GBP employment income; sold-to-cover information does not reduce it."
            else:
                explanation = "Confirm gross taxable GBP vest income and its source."
        lines.append(RsuLine(record, disposition, explanation, amount, line.replaced_by))

    _reconcile_payroll(lines, employment, warnings)
    status: ResultStatus = resolved.status
    priorities: tuple[ProblemStatus, ...] = ("incomplete", "unsupported", "input_error")
    for candidate in priorities:
        if any(warning.status == candidate for warning in warnings):
            status = candidate
    return RsuResult(status, rules.version, rules.tax_year.dates, employment, tuple(lines), tuple(warnings))
