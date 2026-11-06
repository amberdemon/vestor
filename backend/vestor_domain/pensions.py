"""M1 payroll pension treatment and dated personal deductions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from typing import Literal

from .employment import EmploymentLine, EmploymentResult, PayEvent, PayKind, PayrollMethod, SalaryPayment, SalaryPeriod
from .events import DatedMoney, Disposition, ResultStatus, SourceStatus, _require_text, _source_status, resolve_events
from .primitives import DateRange, InputError, Problem, validate_gbp
from .tax_year import TaxRules


@dataclass(frozen=True)
class PayrollReduction:
    reduction_id: str
    pay_id: str
    method: PayrollMethod
    treatment: Literal["apply", "reflected"]
    source_status: SourceStatus
    source_note: str
    qualifies: bool | None
    fixed_gbp: Decimal | None = None
    percent: Decimal | None = None
    base: Literal["full_pay", "stated_amount"] | None = None
    eligible_gbp: Decimal | None = None
    elected_on: date | None = None
    effective_on: date | None = None
    through: date | None = None
    deducted_on: date | None = None

    def __post_init__(self) -> None:
        _require_text(self.reduction_id, "reduction_id")
        _require_text(self.pay_id, "pay_id")
        _require_text(self.source_note, "source_note")
        _source_status(self.source_status)
        _check_evidence(self.qualifies, self.elected_on, self.effective_on, self.through, self.deducted_on)
        if self.method not in ("salary_sacrifice", "net_pay"):
            raise InputError("method", "Use salary sacrifice or net pay.")
        if self.treatment not in ("apply", "reflected"):
            raise InputError("treatment", "Specify whether the payroll reduction is already reflected.")
        validate_gbp(self.fixed_gbp, field="fixed_gbp")
        validate_gbp(self.eligible_gbp, field="eligible_gbp")
        if self.percent is not None:
            value = self.percent
            if (
                not isinstance(value, Decimal) or not value.is_finite() or value.is_signed()
                or value > 100 or int(value.as_tuple().exponent) < -4
            ):
                raise InputError("percent", "Use a Decimal percentage from 0 to 100 with up to four fractional digits.")
            if self.fixed_gbp is not None or self.treatment == "reflected":
                raise InputError("percent", "Use a single amount or percentage, and a fixed amount for reflected payroll evidence.")
        if self.base not in (None, "full_pay", "stated_amount") or (
            self.eligible_gbp is not None and self.base != "stated_amount"
        ):
            raise InputError("base", "Specify full pay or a stated eligible amount.")
        if self.through is not None and (self.effective_on is None or self.through < self.effective_on):
            raise InputError("through", "Supply an end date on or after the effective date.")
        if self.method == "net_pay" and any((self.elected_on, self.effective_on, self.through)):
            raise InputError("deducted_on", "Use the payroll deduction date for net pay.")
        if self.method == "salary_sacrifice" and self.deducted_on is not None:
            raise InputError("deducted_on", "Use the prospective election and effective dates for salary sacrifice.")


@dataclass(frozen=True)
class Adjustment:
    money: DatedMoney
    kind: Literal["relief_at_source", "gross_pension", "gift_aid", "employer"]
    qualifies: bool | None = None
    effective_date_known: bool = True
    provider_gross_gbp: Decimal | None = None
    recorded_on: date | None = None

    def __post_init__(self) -> None:
        _check_evidence(self.qualifies, self.recorded_on)
        if type(self.effective_date_known) is not bool:
            raise InputError("effective_date_known", "Confirm whether the effective date is known.")
        if self.kind not in ("relief_at_source", "gross_pension", "gift_aid", "employer"):
            raise InputError("kind", "Select a supported contribution or donation method.")
        validate_gbp(self.provider_gross_gbp, field="provider_gross_gbp")
        if self.provider_gross_gbp is not None and (
            self.kind != "relief_at_source" or self.money.source_status != "actual"
            or self.money.amount_gbp is not None and self.provider_gross_gbp < self.money.amount_gbp
        ):
            raise InputError("provider_gross_gbp", "Use a confirmed relief-at-source gross amount at least as large as the net payment.")


def _check_evidence(qualifies: bool | None, *dates: date | None) -> None:
    if qualifies is not None and type(qualifies) is not bool:
        raise InputError("qualifies", "Confirm whether the applicable eligibility requirements are met.")
    if any(day is not None and type(day) is not date for day in dates):
        raise InputError("date", "Use date-only evidence.")


@dataclass(frozen=True)
class ReductionLine:
    source: PayrollReduction
    covered: DateRange | None
    eligible_gbp: Fraction | None
    contribution_gbp: Fraction | None
    applied_gbp: Fraction | None


@dataclass(frozen=True)
class TaxablePayLine:
    employment: EmploymentLine
    reductions: tuple[ReductionLine, ...]
    taxable_gbp: Fraction | None


@dataclass(frozen=True)
class AdjustmentLine:
    source: Adjustment
    disposition: Disposition | Literal["unresolved"]
    replaced_by: str | None
    gross_gbp: Fraction | None


@dataclass(frozen=True)
class PensionResult:
    status: ResultStatus
    rule_version: str
    tax_year: DateRange
    basic_relief_rate: Decimal
    employment_lines: tuple[TaxablePayLine, ...]
    adjustment_lines: tuple[AdjustmentLine, ...]
    payroll_sources: tuple[PayrollReduction, ...]
    warnings: tuple[Problem, ...]

    def _taxable(self, kind: PayKind) -> Fraction | None:
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum(
            (line.taxable_gbp for line in self.employment_lines
             if line.employment.kind == kind and line.taxable_gbp is not None),
            Fraction(0),
        )

    @property
    def taxable_salary_gbp(self) -> Fraction | None:
        return self._taxable("salary")

    @property
    def taxable_bonus_gbp(self) -> Fraction | None:
        return self._taxable("bonus")

    def _deductions(self, kinds: tuple[str, ...]) -> Fraction | None:
        if self.status not in ("confirmed", "estimated"):
            return None
        return sum(
            (line.gross_gbp for line in self.adjustment_lines
             if line.source.kind in kinds and line.gross_gbp is not None),
            Fraction(0),
        )

    @property
    def net_income_deduction_gbp(self) -> Fraction | None:
        return self._deductions(("gross_pension",))

    @property
    def ani_deduction_gbp(self) -> Fraction | None:
        return self._deductions(("relief_at_source", "gift_aid"))


def _employment_id(line: EmploymentLine) -> str:
    source = line.source
    if isinstance(source, SalaryPeriod):
        return source.period_id
    if isinstance(source, SalaryPayment):
        return source.pay.money.event_id
    return source.money.event_id


def _sacrifice_dates(reduction: PayrollReduction) -> DateRange | None:
    if reduction.effective_on is None:
        return None
    return DateRange(reduction.effective_on, reduction.through or date.max)


def _check_payroll_links(
    reductions: dict[str, list[PayrollReduction]], employment: EmploymentResult, warnings: list[Problem],
) -> None:
    by_id: dict[str, set[SalaryPeriod | SalaryPayment | PayEvent]] = defaultdict(set)
    for line in employment.lines:
        by_id[_employment_id(line)].add(line.source)
    for pay_id, records in reductions.items():
        sources = by_id.get(pay_id)
        if sources is None or len(sources) != 1:
            warnings.append(Problem("input_error", pay_id, "Link each reduction to one unambiguous employment record."))
            continue
        source, = sources
        if isinstance(source, SalaryPeriod):
            if any(item.method != "salary_sacrifice" or item.treatment != "apply" for item in records):
                warnings.append(Problem("input_error", pay_id, "Use dated payroll for net pay and reflected contributions."))
            schedules = sorted(
                (clipped for item in records if (schedule := _sacrifice_dates(item))
                 and (clipped := schedule.intersection(source.dates))), key=lambda dates: dates.start,
            )
            if any(left.intersection(right) for left, right in pairwise(schedules)):
                warnings.append(Problem("input_error", pay_id, "Salary sacrifice schedules cannot overlap."))
        elif len({item.method for item in records}) != len(records):
            warnings.append(Problem("input_error", pay_id, "Supply one reduction per method for each dated pay record."))


def _apply_reduction(
    line: EmploymentLine, item: PayrollReduction, remaining: Fraction | None, year: DateRange,
    warnings: list[Problem], *, reflected_net_pay: ReductionLine | None = None,
) -> ReductionLine | None:
    covered = None
    annual = isinstance(line.source, SalaryPeriod)
    schedule = _sacrifice_dates(item)
    if annual and schedule is not None and line.covered is not None:
        covered = line.covered.intersection(schedule)
        if covered is None:
            return None
    empty = ReductionLine(item, covered, None, None, None)

    def issue(status: Literal["input_error", "incomplete", "unsupported"], message: str) -> ReductionLine:
        warnings.append(Problem(status, item.reduction_id, message))
        return empty

    if line.basis != "unknown" and (item.method in line.reflected_methods) != (item.treatment == "reflected"):
        return issue("input_error", "The reduction treatment conflicts with the stated payroll basis.")
    if item.qualifies is False:
        return issue("unsupported", "The declared pension treatment does not meet eligibility requirements.")
    if item.qualifies is None or item.source_status == "unknown":
        return issue("incomplete", "Confirm the pension eligibility and source evidence.")
    if item.method == "net_pay":
        pay = line.source.pay if isinstance(line.source, SalaryPayment) else line.source
        if item.deducted_on is None:
            return issue("incomplete", "Confirm the actual or expected net-pay payroll deduction date.")
        if not isinstance(pay, SalaryPeriod) and pay.timing == "payment_date" and item.deducted_on != pay.money.on:
            return issue("input_error", "Reconcile the net-pay deduction date with the linked payroll payment.")
        if item.treatment == "apply" and item.deducted_on not in year:
            return issue("unsupported", "Net pay and taxable receipt fall in different tax years.")
    if item.treatment == "reflected":
        if item.fixed_gbp is None:
            return issue("incomplete", "Confirm the fixed contribution already reflected in payroll.")
        return replace(empty, contribution_gbp=Fraction(item.fixed_gbp), applied_gbp=Fraction(0))
    if remaining is None or line.amount_gbp is None:
        return empty
    if item.method == "salary_sacrifice":
        # HMRC EIM42765 requires contractual change before taxable receipt.
        if schedule is None or item.elected_on is None:
            return issue("incomplete", "Confirm the election and effective dates for salary sacrifice.")
        if isinstance(line.source, SalaryPeriod):
            if item.elected_on >= max(line.source.dates.start, schedule.start):
                return issue("input_error", "The salary election must precede the first affected service day.")
        elif line.receipt_on is None or line.receipt_on not in schedule or schedule.start >= line.receipt_on:
            return issue("input_error", "The sacrifice must take effect before the taxable entitlement or earlier payment.")
        if item.elected_on > schedule.start:
            return issue("input_error", "The election cannot follow the effective date.")
    available = remaining
    if item.method == "salary_sacrifice" and "net_pay" in line.reflected_methods:
        if reflected_net_pay is None or reflected_net_pay.contribution_gbp is None:
            return issue("incomplete", "Confirm the reflected net-pay amount to establish pre-sacrifice pay.")
        available += reflected_net_pay.contribution_gbp
    if item.base is None or (item.base == "stated_amount" and item.eligible_gbp is None):
        return issue("incomplete", "Confirm the eligible pay base for this payroll reduction.")
    if item.fixed_gbp is None and item.percent is None:
        return issue("incomplete", "Confirm the fixed amount or rate of the payroll reduction.")
    weight = Fraction(1)
    if covered is not None and line.covered is not None:
        available = line.amount_gbp * covered.days / line.covered.days
        remaining = available
        weight = Fraction(covered.days, year.days)
    eligible = Fraction(item.eligible_gbp) * weight if item.eligible_gbp is not None else available
    if eligible > available:
        return issue("input_error", "The stated eligible base exceeds the available pay.")
    contribution = (
        Fraction(item.fixed_gbp) * weight if item.fixed_gbp is not None
        else eligible * Fraction(item.percent or 0) / 100
    )
    if contribution > min(eligible, remaining):
        return issue("input_error", "The reduction exceeds the remaining eligible pay.")
    return ReductionLine(item, covered, eligible, contribution, contribution)


def _adjustment_lines(
    adjustments: tuple[Adjustment, ...], rules: TaxRules, warnings: list[Problem],
) -> tuple[tuple[AdjustmentLine, ...], ResultStatus]:
    by_id = {item.money.event_id: item for item in adjustments}
    for item in adjustments:
        target = by_id.get(item.money.replaces_forecast_id or "")
        if target is not None and target.kind != item.kind:
            warnings.append(Problem("input_error", item.money.event_id, "Replace a forecast of the same contribution method."))
    resolved = resolve_events(
        (replace(item.money, amount_gbp=item.provider_gross_gbp) if item.provider_gross_gbp is not None else item.money
         for item in adjustments),
        rules, coverage_confirmed=True,
    )
    warnings.extend(resolved.warnings)
    gross_multiplier = Fraction(1) / (1 - Fraction(rules.basic_relief_rate))
    lines = []
    for evidence in resolved.breakdown:
        item = by_id[evidence.event_id]
        disposition: Disposition | Literal["unresolved"] = evidence.disposition
        gross = None
        if disposition != "replaced" and not item.effective_date_known:
            warnings.append(Problem("incomplete", evidence.event_id, "Confirm the effective payment or donation date."))
            disposition = "unresolved"
        if disposition == "included":
            if item.kind != "employer" and item.qualifies is not True:
                warnings.append(Problem(
                    "unsupported" if item.qualifies is False else "incomplete", evidence.event_id,
                    "Confirm that the contribution or donation qualifies for relief.",
                ))
            elif item.money.source_status != "unknown":
                amount = item.money.amount_gbp
                if item.provider_gross_gbp is not None:
                    gross = Fraction(item.provider_gross_gbp)
                elif amount is not None:
                    gross = Fraction(amount)
                    if item.kind in ("relief_at_source", "gift_aid"):
                        gross *= gross_multiplier
        lines.append(AdjustmentLine(item, disposition, evidence.replaced_by, gross))
    return tuple(lines), resolved.status


def calculate_pensions(
    rules: TaxRules,
    employment: EmploymentResult,
    *,
    payroll_reductions: Iterable[PayrollReduction],
    adjustments: Iterable[Adjustment],
    coverage_confirmed: bool,
) -> PensionResult:
    """Apply payroll reductions once and expose personal deductions by waterfall step."""
    year = rules.tax_year.dates
    warnings = list(employment.warnings)
    if employment.rule_version != rules.version or employment.tax_year != year:
        warnings.append(Problem("input_error", "tax_year", "Use employment evidence from the selected rules and year."))
    if not coverage_confirmed:
        warnings.append(Problem("incomplete", "pension_coverage", "Confirm all contributions, donations or their absence."))
    personal = tuple(adjustments)
    payroll = tuple(sorted(payroll_reductions, key=lambda item: (
        item.method != "salary_sacrifice", item.effective_on or date.min, item.reduction_id,
    )))
    ids = [item.reduction_id for item in payroll] + [item.money.event_id for item in personal]
    if len(set(ids)) != len(ids):
        warnings.append(Problem("input_error", "event_id", "Each contribution or donation ID must occur once."))

    by_pay_id: dict[str, list[PayrollReduction]] = defaultdict(list)
    for item in payroll:
        by_pay_id[item.pay_id].append(item)
    _check_payroll_links(by_pay_id, employment, warnings)
    employment_lines = []
    estimated = employment.status == "estimated"
    for line in employment.lines:
        reductions = []
        remaining = line.amount_gbp
        records = by_pay_id.get(_employment_id(line), ())
        if line.disposition == "included":
            # Recover pre-net-pay pay if a linked salary sacrifice still needs
            # to be applied. The reflected deduction itself contributes zero.
            prior_net = next((item for item in records if item.method == "net_pay" and item.treatment == "reflected"), None)
            reflected = (
                _apply_reduction(line, prior_net, remaining, year, warnings)
                if prior_net is not None else None
            )
            for item in records:
                applied = (
                    reflected if item is prior_net else
                    _apply_reduction(line, item, remaining, year, warnings, reflected_net_pay=reflected)
                )
                if applied is not None:
                    reductions.append(applied)
                    estimated |= item.source_status == "forecast"
                    remaining = (
                        None if remaining is None or applied.applied_gbp is None
                        else remaining - applied.applied_gbp
                    )
        elif line.disposition == "excluded":
            for item in records:
                if (
                    item.method == "net_pay" and item.treatment == "apply"
                    and item.deducted_on is not None and item.deducted_on in year
                ):
                    warnings.append(Problem("unsupported", item.reduction_id, "Net pay and taxable receipt fall in different tax years."))
        employment_lines.append(TaxablePayLine(line, tuple(reductions), remaining))
    adjustment_lines, adjustment_status = _adjustment_lines(personal, rules, warnings)

    status: ResultStatus = "estimated" if estimated or adjustment_status == "estimated" else "confirmed"
    for blocking in ("incomplete", "unsupported", "input_error"):
        if any(warning.status == blocking for warning in warnings):
            status = blocking
    return PensionResult(status, rules.version, year, rules.basic_relief_rate, tuple(employment_lines),
                         adjustment_lines, payroll, tuple(warnings))
