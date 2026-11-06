from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from vestor_domain.employment import (
    PayEvent,
    PayrollComponent,
    SalaryPayment,
    SalaryPeriod,
    calculate_employment,
)
from vestor_domain.events import DatedMoney
from vestor_domain.primitives import DateRange, InputError
from vestor_domain.tax_year import TaxRules, TaxYear, select_tax_rules


def dates(start, end):
    return DateRange(date.fromisoformat(start), date.fromisoformat(end))


def period(key, amount, start="2026-04-06", end="2027-04-05", **changes):
    return replace(
        SalaryPeriod(key, dates(start, end), Decimal(amount) if amount is not None else None,
                     "actual", "Synthetic contract", "monthly"),
        **changes,
    )


def pay(key, amount, on="2027-04-05", *, source="actual", replaces=None, **changes):
    return replace(
        PayEvent(DatedMoney(key, date.fromisoformat(on),
                            Decimal(amount) if amount is not None else None,
                            source, "Synthetic pay evidence", replaces),
                 timing="payment_date", basis="before_reductions"),
        **changes,
    )


def payroll(event, start, end, *, replaces=(), components=()):
    return SalaryPayment(event, dates(start, end), replaces, components)


def calculate(*, salary=(), bonuses=(), payroll=(), bonuses_confirmed=True, year=2026):
    rules = select_tax_rules(2026, "england", standard_treatment=True)
    assert isinstance(rules, TaxRules)
    # Synthetic alternate year exercises day weighting without enabling another tax ruleset.
    if year != 2026:
        rules = replace(rules, tax_year=TaxYear(year))
    return calculate_employment(
        rules, salary_periods=salary, salary_payments=payroll, bonuses=bonuses,
        bonus_coverage_confirmed=bonuses_confirmed,
    )


@pytest.mark.parametrize(("annual", "bonus", "expected"), [
    ("80000", None, (80000, 0)),  # F1 before any pension treatment.
    ("95000", "10000", (95000, 10000)),  # F2 before any pension treatment.
])
def test_full_year_gross_fixtures(annual, bonus, expected):
    bonuses = [] if bonus is None else [pay("bonus", bonus)]
    result = calculate(salary=[period("salary", annual)], bonuses=bonuses)
    assert result.status == "estimated"
    assert (result.gross_salary_gbp, result.gross_bonus_gbp) == expected
    assert result.rule_version == "uk-eng-ni-2026-27-v1"
    assert result.lines[0].covered.days == 365
    assert result.lines[0].method == "calendar_day_estimate"
    assert result.lines[0].source.pay_frequency == "monthly"


def test_rates_split_at_raises_and_keep_exact_day_fractions():
    result = calculate(salary=[
        period("raise2", "100000.03", "2027-01-01", "2027-05-01"),
        period("initial", "80000.01", "2026-01-01", "2026-06-30"),
        period("raise1", "90000.02", "2026-07-01", "2026-12-31"),
    ])
    assert [line.covered.days for line in result.lines] == [86, 184, 95]
    assert result.gross_salary_gbp == Fraction(3294000739, 36500)


@pytest.mark.parametrize(("year", "start", "join", "end", "annual", "expected"), [
    (2026, "2026-04-06", "2026-11-01", "2027-04-05", "73000", 31200),
    (2023, "2023-04-06", "2024-02-29", "2024-04-05", "36600", 3700),
])
def test_joiner_has_explicit_unpaid_coverage_and_correct_year_denominator(
    year, start, join, end, annual, expected,
):
    preceding_day = date.fromordinal(date.fromisoformat(join).toordinal() - 1).isoformat()
    result = calculate(year=year, salary=[
        period("not-employed", "0", start, preceding_day),
        period("employed", annual, join, end),
    ])
    assert result.gross_salary_gbp == expected
    assert result.lines[0].method == "unpaid"


def test_leaver_with_unexplained_gap_is_incomplete():
    result = calculate(salary=[period("left", "73000", end="2026-11-30")])
    assert result.status == "incomplete"
    assert result.gross_salary_gbp is None
    assert result.lines[0].amount_gbp == 47800
    assert any(warning.field == "salary_coverage" for warning in result.warnings)


def test_same_day_salary_overlap_is_rejected():
    result = calculate(salary=[
        period("old", "73000", end="2026-11-01"),
        period("raise", "83000", start="2026-11-01"),
    ])
    assert result.status == "input_error"
    assert result.gross_salary_gbp is None


def test_salary_rate_with_unknown_value_is_incomplete():
    result = calculate(salary=[period("salary", None)])
    assert result.status == "incomplete"
    assert result.gross_salary_gbp is None


def test_bonus_receipt_boundaries_f10():
    result = calculate(salary=[period("salary", "80000")], bonuses=[
        pay("prior", "2000", "2026-03-31"),
        pay("first", "3000", "2026-04-06"),
        pay("last", "500", "2027-04-05"),
        pay("next", "4000", "2027-04-06"),
    ])
    assert result.gross_salary_gbp == 80000
    assert result.gross_bonus_gbp == 3500
    assert [line.disposition for line in result.lines[1:]] == [
        "excluded", "included", "included", "excluded",
    ]


@pytest.mark.parametrize(("actual_on", "expected"), [("2027-04-05", 1200), ("2027-04-06", 0)])
def test_bonus_actual_replaces_forecast_before_year_filter(actual_on, expected):
    result = calculate(salary=[period("unpaid", "0")], bonuses=[
        pay("estimate", "1000", source="forecast"),
        pay("payslip", "1200", actual_on, replaces="estimate"),
    ])
    assert result.status == "confirmed"
    assert result.gross_bonus_gbp == expected
    replaced = next(line for line in result.lines if line.disposition == "replaced")
    assert replaced.replaced_by == "payslip"
    assert replaced.source.money.amount_gbp == Decimal("1000")


@pytest.mark.parametrize("source", ["actual", "forecast"])
def test_earlier_entitlement_controls_bonus_year(source):
    result = calculate(salary=[period("unpaid", "0")], bonuses=[
        pay("bonus", "900", "2027-04-06", source=source, entitlement_on=date(2027, 4, 5)),
    ])
    assert result.gross_bonus_gbp == 900
    assert result.lines[-1].receipt_on == date(2027, 4, 5)


@pytest.mark.parametrize("on", ["2027-04-05", "2027-04-06"])
def test_material_unconfirmed_actual_entitlement_blocks_total(on):
    result = calculate(salary=[period("unpaid", "0")], bonuses=[
        pay("bonus", "1000", on, timing="unconfirmed_entitlement"),
    ])
    assert result.status == "incomplete"
    assert result.gross_bonus_gbp is None
    assert result.lines[-1].receipt_on is None


def test_bonus_absence_requires_explicit_confirmation():
    result = calculate(salary=[period("unpaid", "0")], bonuses_confirmed=False)
    assert result.status == "incomplete"
    assert result.gross_bonus_gbp is None


def test_negative_bonus_is_a_field_error():
    with pytest.raises(InputError, match="nonnegative"):
        pay("bonus", "-0.01")


@pytest.mark.parametrize(("payment_on", "expected"), [("2027-04-05", 73400), ("2027-04-06", 72800)])
def test_actual_pay_covers_days_even_if_receipt_moves_to_next_year(payment_on, expected):
    result = calculate(salary=[period("rate", "73000")], payroll=[
        payroll(pay("payslip", "600", payment_on), "2027-04-05", "2027-04-05", replaces=("rate",)),
    ])
    assert result.gross_salary_gbp == expected
    rate_lines = [line for line in result.lines if isinstance(line.source, SalaryPeriod)]
    assert [(line.disposition, line.covered.days) for line in rate_lines] == [
        ("included", 364), ("replaced", 1),
    ]
    assert rate_lines[1].replaced_by == "payslip"


def test_forecast_pay_schedule_uses_dated_amount_and_receipt():
    result = calculate(payroll=[
        payroll(pay("scheduled", "73000", source="forecast"), "2026-04-06", "2027-04-05"),
    ])
    assert result.status == "estimated"
    assert result.gross_salary_gbp == 73000
    assert result.lines[0].receipt_on == date(2027, 4, 5)


def test_unlinked_payroll_overlap_blocks_double_counting():
    result = calculate(salary=[period("rate", "73000")], payroll=[
        payroll(pay("payslip", "600"), "2027-04-05", "2027-04-05"),
    ])
    assert result.status == "incomplete"
    assert result.gross_salary_gbp is None


def test_known_payroll_composition_preserves_total_and_counts_bonus_once():
    result = calculate(
        payroll=[payroll(pay("payslip", "90000"), "2026-04-06", "2027-04-05", components=(
            PayrollComponent("annual-bonus", "bonus", Decimal("5000")),
            PayrollComponent("rsu-award", "rsu", Decimal("8000")),
            PayrollComponent("medical", "benefit", Decimal("2000")),
        ))],
        bonuses=[pay("annual-bonus", "5000")],
    )
    assert result.status == "confirmed"
    assert (result.gross_salary_gbp, result.gross_bonus_gbp) == (75000, 5000)
    salary_line = next(line for line in result.lines if line.kind == "salary")
    assert salary_line.source.pay.money.amount_gbp == Decimal("90000")


@pytest.mark.parametrize(("components", "status"), [
    (None, "incomplete"),
    ((PayrollComponent("benefit", "benefit", None),), "incomplete"),
    ((PayrollComponent("missing", "bonus", Decimal("1")),), "incomplete"),
    ((PayrollComponent("benefit", "benefit", Decimal("90001")),), "input_error"),
    ((PayrollComponent("annual-bonus", "bonus", Decimal("4999")),), "incomplete"),
])
def test_payroll_composition_must_be_known_and_consistent(components, status):
    result = calculate(
        payroll=[payroll(pay("payslip", "90000"), "2026-04-06", "2027-04-05", components=components)],
        bonuses=[pay("annual-bonus", "5000")],
    )
    assert result.status == status
    assert result.gross_salary_gbp is None


def test_pay_after_pension_reductions_is_retained_with_basis():
    result = calculate(payroll=[
        payroll(pay("payslip", "100000", basis="after_reductions"), "2026-04-06", "2027-04-05"),
    ])
    assert result.status == "confirmed"
    assert result.gross_salary_gbp is None
    assert result.lines[0].amount_gbp == 100000
    assert result.lines[0].source.pay.basis == "after_reductions"


def test_dated_salary_override_keeps_rate_coverage_links_when_receipt_moves():
    result = calculate(salary=[period("rate", "73000")], payroll=[
        payroll(pay("forecast", "500", source="forecast"),
                "2027-04-05", "2027-04-05", replaces=("rate",)),
        payroll(pay("actual", "600", "2027-04-06", replaces="forecast"),
                "2027-04-05", "2027-04-05"),
    ])
    assert result.status == "estimated"
    assert result.gross_salary_gbp == 72800


def test_excluded_payroll_still_reconciles_an_in_year_linked_bonus():
    result = calculate(salary=[period("unpaid", "0")], payroll=[
        payroll(pay("payslip", "800", "2027-04-06"), "2027-04-06", "2027-04-06", components=(
            PayrollComponent("bonus", "bonus", Decimal("799")),
        )),
    ], bonuses=[pay("bonus", "800", "2027-04-06", entitlement_on=date(2027, 4, 5))])
    assert result.status == "incomplete"
    assert result.gross_bonus_gbp is None


def test_uncertain_receipt_is_not_presented_as_included_or_excluded():
    result = calculate(salary=[period("unpaid", "0")], bonuses=[
        pay("bonus", "500", "2027-04-06", timing="unconfirmed_entitlement"),
    ])
    assert result.lines[-1].disposition == "unresolved"


@pytest.mark.parametrize(("source", "status"), [("forecast", "estimated"), ("unknown", "incomplete")])
def test_out_of_year_pay_still_affects_in_year_salary_coverage(source, status):
    result = calculate(payroll=[
        payroll(pay("salary", "73000", "2027-04-06", source=source), "2026-04-06", "2027-04-05"),
    ])
    assert result.status == status


def test_unknown_payment_date_keeps_only_reference_evidence():
    result = calculate(salary=[period("unpaid", "0")], bonuses=[
        pay("bonus", "500", "2026-04-05", timing="unknown_date"),
        pay("other-bonus", "1000"),
    ])
    assert result.status == "incomplete"
    assert result.gross_bonus_gbp is None
    unresolved, known = result.lines[1:]
    assert unresolved.receipt_on is None
    assert unresolved.disposition == "unresolved"
    assert known.amount_gbp == 1000


def test_salary_payment_covers_only_its_part_of_multiple_rate_periods():
    result = calculate(
        salary=[
            period("old", "73000", end="2026-11-30"),
            period("new", "109500", start="2026-12-01"),
        ],
        payroll=[payroll(pay("payslip", "700", "2026-12-01"),
                         "2026-11-30", "2026-12-01", replaces=("old", "new"))],
    )
    # 238 days at £200/day, 125 days at £300/day and £700 actual.
    assert result.gross_salary_gbp == 85800


@pytest.mark.parametrize(("bonus_timing", "bonus_on", "entitlement_on", "expected"), [
    ("payment_date", "2027-04-06", None, None),
    ("payment_date", "2027-04-06", date(2027, 4, 5), None),
    ("confirmed_receipt", "2027-04-06", None, None),
    ("payment_date", "2027-04-05", date(2027, 4, 4), 1000),
    ("confirmed_receipt", "2027-04-04", None, 1000),
])
def test_payroll_inclusion_reconciles_bonus_dates(bonus_timing, bonus_on, entitlement_on, expected):
    result = calculate(
        payroll=[payroll(pay("payslip", "81000"), "2026-04-06", "2027-04-05", components=(
            PayrollComponent("bonus", "bonus", Decimal("1000")),
        ))],
        bonuses=[pay("bonus", "1000", bonus_on, timing=bonus_timing, entitlement_on=entitlement_on)],
    )
    assert result.gross_bonus_gbp == expected
    if expected is None:
        assert result.status == "incomplete"
        assert result.gross_salary_gbp is None
        assert any(warning.field == "payslip" for warning in result.warnings)
    else:
        assert result.status == "confirmed"
        assert result.gross_salary_gbp == 80000


def test_payroll_receipt_due_to_entitlement_does_not_establish_a_payment_date():
    result = calculate(
        payroll=[payroll(pay("payslip", "81000", timing="confirmed_receipt"),
                         "2026-04-06", "2027-04-05", components=(
                             PayrollComponent("bonus", "bonus", Decimal("1000")),
                         ))],
        bonuses=[pay("bonus", "1000", "2027-04-06", entitlement_on=date(2027, 4, 4))],
    )
    assert result.status == "confirmed"
    assert result.gross_bonus_gbp == 1000


@pytest.mark.parametrize(("bonus_on", "expected_status", "expected_bonus"), [
    ("2026-04-05", "confirmed", 0),
    ("2026-04-06", "incomplete", None),
])
def test_prior_year_payroll_reconciles_linked_bonus_if_it_enters_selected_year(
    bonus_on, expected_status, expected_bonus,
):
    result = calculate(salary=[period("unpaid", "0")], payroll=[
        payroll(pay("payslip", "81000", "2026-04-05"), "2026-03-01", "2026-04-05", components=(
            PayrollComponent("bonus", "bonus", Decimal("1000")),
        )),
        payroll(pay("unrelated", "80000", "2026-02-28"), "2026-02-01", "2026-02-28", components=None),
    ], bonuses=[pay("bonus", "1000", bonus_on)])

    assert result.status == expected_status
    assert result.gross_bonus_gbp == expected_bonus
    assert {warning.field for warning in result.warnings} == (
        {"payslip"} if expected_status == "incomplete" else set()
    )
