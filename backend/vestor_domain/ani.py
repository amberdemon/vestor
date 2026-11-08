"""Pure M1 ANI entry point; all money remains exact until presentation."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast

from .benefits import BenefitPeriod, BenefitResult, calculate_benefits
from .employment import PayEvent, SalaryPayment, SalaryPeriod, calculate_employment
from .events import ResultStatus
from .other_income import OtherIncome, OtherIncomeResult, calculate_other_income
from .pensions import Adjustment, PayrollReduction, PensionResult, calculate_pensions
from .primitives import InputError, Problem, validate_gbp
from .rsu import RsuEvent, RsuResult, calculate_rsu_income
from .tax_year import TaxRules, select_tax_rules

ANI_SOURCE = "https://www.gov.uk/guidance/adjusted-net-income"
ALLOWANCE_SOURCE = "https://www.legislation.gov.uk/ukpga/2007/3/section/35/data.html"


@dataclass(frozen=True)
class AniInputs:
    start_year: int | None
    jurisdiction: str | None
    standard_treatment: bool | None
    salary_periods: tuple[SalaryPeriod, ...] = ()
    salary_payments: tuple[SalaryPayment, ...] = ()
    bonuses: tuple[PayEvent, ...] = ()
    payroll_reductions: tuple[PayrollReduction, ...] = ()
    adjustments: tuple[Adjustment, ...] = ()
    benefits: tuple[BenefitPeriod, ...] = ()
    rsu_events: tuple[RsuEvent, ...] = ()
    other_income: tuple[OtherIncome, ...] = ()
    bonus_coverage_confirmed: bool = False
    pension_coverage_confirmed: bool = False
    benefit_coverage_confirmed: bool = False
    rsu_coverage_confirmed: bool = False
    other_income_coverage_confirmed: bool = False
    target_gbp: Decimal | None = Decimal("100000")

    def __post_init__(self) -> None:
        validate_gbp(self.target_gbp, field="target_gbp")


@dataclass(frozen=True)
class WaterfallRow:
    key: str
    amount_gbp: Fraction | None
    status: ResultStatus
    evidence_path: str
    explanation: str


@dataclass(frozen=True)
class AniResult:
    status: ResultStatus
    inputs: AniInputs
    rules: TaxRules | None
    rows: tuple[WaterfallRow, ...]
    pensions: PensionResult | None
    benefits: BenefitResult | None
    rsu: RsuResult | None
    other_income: OtherIncomeResult | None
    taxable_income_gbp: Fraction | None
    net_income_gbp: Fraction | None
    ani_gbp: Fraction | None
    personal_allowance_gbp: Fraction | None
    headroom_gbp: Fraction | None
    rounding_discrepancy_gbp: Fraction | None
    warnings: tuple[Problem, ...]
    assumptions: tuple[str, ...] = (
        "Salary and supported annual benefits use inclusive calendar-day forecasts unless replaced by dated evidence.",
        "Payroll sacrifice and net pay reduce employment pay once; employer funding is not an ANI deduction.",
        "Qualifying gross pension reduces net income; gross Gift Aid and relief at source then reduce ANI.",
        "GBP displays round once half-up; totals and the statutory allowance use unrounded exact values.",
        "No income tax/NI payable, CGT liability, spendable cash or optimal pension contribution is calculated.",
    )
    source_urls: tuple[str, ...] = (ANI_SOURCE, ALLOWANCE_SOURCE)
    sources_verified_on: date = date(2026, 11, 8)

    def row(self, key: str) -> WaterfallRow:
        return next(row for row in self.rows if row.key == key)

    def to_wire(self) -> dict[str, Any]:
        return cast(dict[str, Any], _wire(self))


def _pennies(value: Fraction) -> int:
    magnitude = abs(value) * 100
    rounded = (2 * magnitude.numerator + magnitude.denominator) // (2 * magnitude.denominator)
    return -rounded if value < 0 else rounded


def display_gbp(value: Fraction) -> str:
    pennies = _pennies(value)
    return f"{'-' if pennies < 0 else ''}{abs(pennies) // 100}.{abs(pennies) % 100:02d}"


def _wire(value: Any) -> Any:
    """Retain exact fractions and all dated source evidence without JSON floats."""
    if isinstance(value, Fraction):
        return {"numerator": str(value.numerator), "denominator": str(value.denominator),
                "display_gbp": display_gbp(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    return value


def _canonical(raw: AniInputs) -> AniInputs:
    def pay(item: PayEvent) -> PayEvent:
        return replace(item, reflected_methods=None if item.reflected_methods is None
                       else tuple(sorted(item.reflected_methods)))

    raw = replace(raw,
        salary_payments=tuple(replace(item, pay=pay(item.pay),
            replaces_period_ids=tuple(sorted(item.replaces_period_ids)),
            components=None if item.components is None else tuple(sorted(item.components, key=lambda c: (c.kind, c.component_id))))
            for item in raw.salary_payments),
        bonuses=tuple(pay(item) for item in raw.bonuses),
        benefits=tuple(replace(item, payroll_ids=tuple(sorted(item.payroll_ids)),
            replaces_forecast_ids=tuple(sorted(item.replaces_forecast_ids))) for item in raw.benefits),
        rsu_events=tuple(replace(item, payroll_ids=tuple(sorted(item.payroll_ids))) for item in raw.rsu_events),
        other_income=tuple(replace(item, coverage_ids=tuple(sorted(item.coverage_ids))) for item in raw.other_income),
    )
    return replace(raw,
        salary_periods=tuple(sorted(raw.salary_periods, key=lambda x: x.period_id)),
        salary_payments=tuple(sorted(raw.salary_payments, key=lambda x: x.pay.money.event_id)),
        bonuses=tuple(sorted(raw.bonuses, key=lambda x: x.money.event_id)),
        payroll_reductions=tuple(sorted(raw.payroll_reductions, key=lambda x: x.reduction_id)),
        adjustments=tuple(sorted(raw.adjustments, key=lambda x: x.money.event_id)),
        benefits=tuple(sorted(raw.benefits, key=lambda x: x.period_id)),
        rsu_events=tuple(sorted(raw.rsu_events, key=lambda x: x.money.event_id)),
        other_income=tuple(sorted(raw.other_income, key=lambda x: x.money.event_id)),
    )


def calculate_ani(raw: AniInputs) -> AniResult:
    """Resolve raw domain evidence through one verified, deterministic waterfall.

    HMRC ANI steps and ITA 2007 s35 reviewed 8 November 2026 for 2026/27.
    Exact rational arithmetic preserves nonterminating day fractions and avoids
    Decimal context affecting the whole-pound ceiling of the remaining allowance.
    """
    raw = _canonical(raw)
    source_ids = ([x.period_id for x in raw.salary_periods]
        + [x.pay.money.event_id for x in raw.salary_payments]
        + [x.money.event_id for x in raw.bonuses]
        + [x.money.event_id for x in raw.adjustments]
        + [x.money.event_id for x in raw.rsu_events]
        + [x.money.event_id for x in raw.other_income]
        + [x.reduction_id for x in raw.payroll_reductions]
        + [x.period_id for x in raw.benefits])
    if len(source_ids) != len(set(source_ids)):
        raise InputError("event_id", "Each source identity must be unique across income and adjustment categories.")
    selected = select_tax_rules(raw.start_year, raw.jurisdiction, standard_treatment=raw.standard_treatment)
    if isinstance(selected, Problem):
        return AniResult(selected.status, raw, None, (), None, None, None, None,
                         None, None, None, None, None, None, (selected,))
    rules = selected
    employment = calculate_employment(rules, salary_periods=raw.salary_periods,
        salary_payments=raw.salary_payments, bonuses=raw.bonuses,
        bonus_coverage_confirmed=raw.bonus_coverage_confirmed)
    pensions = calculate_pensions(rules, employment, payroll_reductions=raw.payroll_reductions,
        adjustments=raw.adjustments, coverage_confirmed=raw.pension_coverage_confirmed)
    benefits = calculate_benefits(rules, benefits=raw.benefits, employment=employment,
                                 coverage_confirmed=raw.benefit_coverage_confirmed)
    rsu = calculate_rsu_income(rules, events=raw.rsu_events, employment=employment,
                               coverage_confirmed=raw.rsu_coverage_confirmed)
    other = calculate_other_income(rules, entries=raw.other_income,
                                    coverage_confirmed=raw.other_income_coverage_confirmed)
    components = (pensions, benefits, rsu, other)
    warnings = tuple(sorted(set(w for component in components for w in component.warnings),
                            key=lambda w: (w.status, w.field, w.message)))
    status: ResultStatus = "confirmed"
    for candidate in ("estimated", "incomplete", "unsupported", "input_error"):
        if any(component.status == candidate for component in components):
            status = candidate
    def pay_status(kind: str) -> ResultStatus:
        if pensions.status not in ("confirmed", "estimated"):
            return pensions.status
        for line in pensions.employment_lines:
            evidence = line.employment
            if evidence.kind != kind or evidence.disposition != "included":
                continue
            source = evidence.source
            source_status = (source.source_status if isinstance(source, SalaryPeriod) else
                source.pay.money.source_status if isinstance(source, SalaryPayment) else source.money.source_status)
            if (evidence.method == "calendar_day_estimate" or source_status == "forecast"
                or any(r.source.source_status == "forecast" for r in line.reductions)):
                return "estimated"
        return "confirmed"

    rows = [
        WaterfallRow("taxable_salary", pensions.taxable_salary_gbp, pay_status("salary"),
                     "pensions.employment_lines", "Salary isolated from payroll components, after payroll reductions."),
        WaterfallRow("taxable_bonus", pensions.taxable_bonus_gbp, pay_status("bonus"),
                     "pensions.employment_lines", "Taxable bonuses after payroll reductions."),
        WaterfallRow("rsu", rsu.taxable_gbp, rsu.status, "rsu.lines", "Gross taxable GBP vest income, including payroll components once."),
        WaterfallRow("benefits", benefits.taxable_gbp, benefits.status, "benefits.lines", "Taxable benefits, including payroll components once."),
        WaterfallRow("other_income", other.taxable_gbp, other.status, "other_income.lines", "Supported taxable income before nil-rate allowances."),
    ]
    for kind, explanation in (
        ("gross_pension", "Qualifying gross pension deduction in HMRC net income."),
        ("gift_aid", "Qualifying grossed-up Gift Aid deduction from net income."),
        ("relief_at_source", "Qualifying gross pension deduction from net income; no duplicate higher-rate relief."),
    ):
        amount = None if pensions.status not in ("confirmed", "estimated") else -sum(
            (line.gross_gbp for line in pensions.adjustment_lines
             if line.source.kind == kind and line.gross_gbp is not None), Fraction(0))
        row_status = pensions.status
        if amount is not None:
            row_status = "estimated" if any(line.source.money.source_status == "forecast"
                for line in pensions.adjustment_lines
                if line.source.kind == kind and line.disposition == "included") else "confirmed"
        rows.append(WaterfallRow(kind, amount, row_status, "pensions.adjustment_lines", explanation))
    taxable = net = ani = allowance = headroom = discrepancy = None
    if status in ("confirmed", "estimated"):
        amounts = [row.amount_gbp for row in rows]
        assert all(amount is not None for amount in amounts)
        known = [amount for amount in amounts if amount is not None]
        taxable = sum(known[:5], Fraction(0))
        net = taxable + known[5]
        ani = net + sum(known[6:], Fraction(0))
        remaining = max(Fraction(rules.allowance_floor_gbp), Fraction(rules.standard_allowance_gbp)
            - max(Fraction(0), ani - Fraction(rules.taper_threshold_gbp)) * Fraction(rules.taper_reduction_per_pound))
        allowance = Fraction(-(-remaining.numerator // remaining.denominator))
        headroom = None if raw.target_gbp is None else Fraction(raw.target_gbp) - ani
        discrepancy = Fraction(_pennies(ani) - sum(_pennies(amount) for amount in known), 100)
    return AniResult(status, raw, rules, tuple(rows), pensions, benefits, rsu, other,
                     taxable, net, ani, allowance, headroom, discrepancy, warnings)
