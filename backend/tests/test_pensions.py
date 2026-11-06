from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from test_employment import calculate, pay, payroll, period
from vestor_domain.events import DatedMoney
from vestor_domain.pensions import Adjustment, PayrollReduction, calculate_pensions
from vestor_domain.tax_year import TaxRules, select_tax_rules


RULES = select_tax_rules(2026, "england", standard_treatment=True)
assert isinstance(RULES, TaxRules)


def pension(employment, reductions=(), adjustments=(), *, confirmed=True):
    return calculate_pensions(
        RULES, employment, payroll_reductions=reductions, adjustments=adjustments,
        coverage_confirmed=confirmed,
    )


def sacrifice(key, pay_id, *, amount=None, percent=None, election="2026-04-01",
              effective="2026-04-02", **kwargs):
    return PayrollReduction(
        key, pay_id, "salary_sacrifice", "apply", "forecast", "Synthetic pension election",
        True, fixed_gbp=None if amount is None else Decimal(amount),
        percent=None if percent is None else Decimal(percent), base="full_pay",
        elected_on=date.fromisoformat(election), effective_on=date.fromisoformat(effective),
        **kwargs,
    )


def net_pay(key, pay_id, amount=None, *, percent=None, treatment="apply", **kwargs):
    return PayrollReduction(
        key, pay_id, "net_pay", treatment, "actual", "Synthetic payslip pension line", True,
        fixed_gbp=None if amount is None else Decimal(amount),
        percent=None if percent is None else Decimal(percent),
        deducted_on=date(2027, 4, 5), **kwargs,
    )


def adjustment(key, kind, amount, on="2027-04-05", *, source="actual", replaces=None, **kwargs):
    return Adjustment(
        DatedMoney(key, date.fromisoformat(on), None if amount is None else Decimal(amount),
                   source, "Synthetic contribution receipt", replaces),
        kind, **kwargs,
    )


def test_f1_full_year_salary_sacrifice():
    result = pension(calculate(salary=[period("salary", "80000")]), [
        sacrifice("sacrifice", "salary", percent="2", through=date(2027, 4, 5)),
    ])
    assert result.taxable_salary_gbp == 78400
    assert result.ani_deduction_gbp == 0
    assert result.employment_lines[0].reductions[0].contribution_gbp == 1600


@pytest.mark.parametrize(("salary", "bonus", "sac", "expected"), [
    ("95000", "10000", "5500", 99500),  # F2b
    ("100000", "1000", "1000", 100000),  # F7a
])
def test_valid_bonus_sacrifice(salary, bonus, sac, expected):
    result = pension(calculate(salary=[period("salary", salary)], bonuses=[pay("bonus", bonus)]), [
        sacrifice("sacrifice", "bonus", amount=sac),
    ])
    assert result.taxable_salary_gbp + result.taxable_bonus_gbp == expected
    assert result.ani_deduction_gbp == 0


def test_f7b_mixed_personal_contributions_and_employer_funding():
    employment = calculate(salary=[period("salary", "100000")], bonuses=[pay("bonus", "1000")])
    ras = adjustment("personal", "relief_at_source", "800", qualifies=True)
    result = pension(employment, adjustments=[ras])
    assert (result.taxable_salary_gbp, result.taxable_bonus_gbp, result.ani_deduction_gbp) == (100000, 1000, 1000)

    result = pension(employment, adjustments=[
        replace(ras, provider_gross_gbp=Decimal("1000")),
        adjustment("gift", "gift_aid", "800", qualifies=True),
        adjustment("gross", "gross_pension", "500", qualifies=True),
        adjustment("employer", "employer", "4000"),
    ])
    assert result.net_income_deduction_gbp == 500
    assert result.ani_deduction_gbp == 2000
    assert result.taxable_salary_gbp == 100000
    assert [line.gross_gbp for line in result.adjustment_lines] == [4000, 1000, 500, 1000]


def test_f7c_confirmed_payroll_evidence_is_not_subtracted_again():
    employment = calculate(payroll=[payroll(pay("salary", "100000", basis="after_reductions"),
                                             "2026-04-06", "2027-04-05")])
    reflected = replace(sacrifice("sacrifice", "salary", amount="2000"),
                        treatment="reflected", source_status="actual")
    result = pension(employment, [reflected, net_pay("net", "salary", "1000", treatment="reflected")])
    assert result.taxable_salary_gbp == 100000
    assert result.ani_deduction_gbp == 0
    assert [line.applied_gbp for line in result.employment_lines[0].reductions] == [0, 0]
    conflict = pension(employment, [sacrifice("sacrifice", "salary", amount="2000")])
    assert conflict.status == "input_error"
    assert conflict.taxable_salary_gbp is None


def test_net_pay_percentage_uses_post_sacrifice_pay():
    employment = calculate(payroll=[payroll(pay("salary", "10000"), "2026-04-06", "2027-04-05")])
    result = pension(employment, [
        net_pay("net", "salary", percent="10", base="full_pay"),
        replace(sacrifice("sacrifice", "salary", amount="500"), base="stated_amount", eligible_gbp=Decimal("4000")),
    ])
    assert result.taxable_salary_gbp == 8550
    assert result.ani_deduction_gbp == 0
    assert [line.contribution_gbp for line in result.employment_lines[0].reductions] == [500, 950]


def test_rate_change_and_payroll_replacement_keep_exact_effective_coverage():
    employment = calculate(salary=[period("salary", "73000")], payroll=[
        payroll(pay("actual", "200", "2026-11-01", basis="after_reductions"),
                "2026-11-01", "2026-11-01", replaces=("salary",)),
    ])
    result = pension(employment, [
        sacrifice("prior", "salary", percent="2", through=date(2026, 10, 31)),
        sacrifice("later", "salary", amount="1000.01", election="2026-10-31",
                  effective="2026-11-01", through=date(2027, 4, 5)),
    ])
    # £4 × 209 days + £1,000.01 × 155 / 365, keeping all fractions.
    assert result.taxable_salary_gbp == 73000 - 836 - Fraction(100001, 100) * 155 / 365
    assert [r.covered.days for line in result.employment_lines for r in line.reductions] == [209, 155]


def test_overlapping_salary_sacrifice_elections_are_rejected():
    employment = calculate(salary=[period("salary", "80000")])
    result = pension(employment, [
        sacrifice("first", "salary", percent="2", through=date(2026, 11, 1)),
        sacrifice("second", "salary", percent="3", election="2026-10-31", effective="2026-11-01"),
    ])
    assert result.status == "input_error"
    assert result.taxable_salary_gbp is None


@pytest.mark.parametrize(("election", "effective", "qualifies"), [
    ("2026-10-31", "2026-11-01", True),  # same effective date as entitlement
    ("2026-11-01", "2026-11-01", True),  # same election date as entitlement
    ("2026-10-29", "2026-10-30", None),  # eligibility missing
    ("2026-10-29", "2026-10-30", False),
    (None, "2026-10-30", True),
])
def test_bonus_sacrifice_requires_prospective_eligibility(election, effective, qualifies):
    employment = calculate(salary=[period("salary", "0")], bonuses=[
        pay("bonus", "10000", entitlement_on=date(2026, 11, 1)),
    ])
    record = replace(sacrifice("sacrifice", "bonus", amount="5500", effective=effective),
                     elected_on=None if election is None else date.fromisoformat(election), qualifies=qualifies)
    result = pension(employment, [record])
    assert result.status in ("incomplete", "unsupported", "input_error")
    assert result.taxable_bonus_gbp is None


def test_personal_effective_date_and_actual_override():
    result = pension(calculate(salary=[period("salary", "101000")]), adjustments=[
        adjustment("last", "relief_at_source", "800", qualifies=True, recorded_on=date(2027, 4, 18)),
        adjustment("first-next", "relief_at_source", "800", "2027-04-06", qualifies=True),
        adjustment("forecast", "gift_aid", "80", source="forecast", qualifies=True),
        adjustment("actual", "gift_aid", "80", "2027-04-06", replaces="forecast", qualifies=True),
        adjustment("last-prior", "gift_aid", "80", "2026-04-05", qualifies=True),
        adjustment("first", "gift_aid", "0.01", "2026-04-06", qualifies=True),
    ])
    assert result.ani_deduction_gbp == 1000 + Fraction(1, 80)
    assert [line.disposition for line in result.adjustment_lines] == [
        "excluded", "included", "replaced", "included", "excluded", "excluded",
    ]


@pytest.mark.parametrize(("record", "status"), [
    (adjustment("gift", "gift_aid", "80"), "incomplete"),
    (adjustment("gift", "gift_aid", "80", qualifies=False), "unsupported"),
    (adjustment("gross", "gross_pension", "50", qualifies=True, effective_date_known=False), "incomplete"),
])
def test_missing_or_unsupported_contribution_evidence_blocks_totals(record, status):
    result = pension(calculate(salary=[period("salary", "100000")]), adjustments=[record])
    assert result.status == status
    assert result.ani_deduction_gbp is None


@pytest.mark.parametrize(("reflected_methods", "amount", "expected"), [
    (("salary_sacrifice",), "9500", 8550),
    (("net_pay",), "9000", 8500),
])
def test_dated_pay_can_state_which_reduction_is_already_reflected(reflected_methods, amount, expected):
    employment = calculate(payroll=[payroll(
        pay("salary", amount, basis="after_reductions", reflected_methods=reflected_methods),
        "2026-04-06", "2027-04-05",
    )])
    if reflected_methods == ("salary_sacrifice",):
        reductions = [net_pay("net", "salary", percent="10", base="full_pay")]
    else:
        reductions = [
            sacrifice("sacrifice", "salary", percent="5"),
            net_pay("net", "salary", "1000", treatment="reflected"),
        ]
    result = pension(employment, reductions)
    assert result.taxable_salary_gbp == expected


def test_net_pay_reflected_requires_amount_before_calculating_sacrifice():
    employment = calculate(payroll=[payroll(
        pay("salary", "9000", basis="after_reductions", reflected_methods=("net_pay",)),
        "2026-04-06", "2027-04-05",
    )])
    result = pension(employment, [sacrifice("sacrifice", "salary", percent="5")])
    assert result.status == "incomplete"
    assert result.taxable_salary_gbp is None


@pytest.mark.parametrize(("deducted", "receipt", "expected"), [
    ("2027-04-05", "2027-04-04", "confirmed"),
    ("2027-04-06", "2027-04-05", "unsupported"),
    ("2027-04-05", "2026-04-05", "unsupported"),
])
def test_net_pay_uses_deduction_date_with_linked_receipt(deducted, receipt, expected):
    employment = calculate(salary=[period("salary", "0")], bonuses=[
        pay("bonus", "1000", receipt, timing="confirmed_receipt"),
    ])
    item = replace(net_pay("net", "bonus", "100", base="full_pay"), deducted_on=date.fromisoformat(deducted))
    result = pension(employment, [item])
    assert result.status == expected
    assert result.taxable_bonus_gbp == (900 if expected == "confirmed" else None)


def test_forecast_pay_reductions_do_not_override_actual_pay():
    employment = calculate(salary=[period("salary", "95000")], bonuses=[
        pay("forecast", "10000", source="forecast"),
        pay("actual", "8000", replaces="forecast", basis="after_reductions"),
    ])
    item = sacrifice("sacrifice", "forecast", amount="5500")
    result = pension(employment, [item])
    assert result.taxable_bonus_gbp == 8000
    assert result.payroll_sources == (item,)
    assert next(line for line in result.employment_lines if line.employment.disposition == "replaced").reductions == ()


def test_contribution_cannot_be_entered_as_both_net_pay_and_gross_pension():
    employment = calculate(salary=[period("salary", "0")], bonuses=[pay("bonus", "1000")])
    result = pension(
        employment, [net_pay("same", "bonus", "100", base="full_pay")],
        [adjustment("same", "gross_pension", "100", qualifies=True)],
    )
    assert result.status == "input_error"
    assert result.net_income_deduction_gbp is None


def test_provider_confirmed_gross_is_sufficient_without_net_cash():
    result = pension(calculate(salary=[period("salary", "101000")]), adjustments=[
        adjustment("pension", "relief_at_source", None, qualifies=True, provider_gross_gbp=Decimal("1000.01")),
    ])
    assert result.ani_deduction_gbp == Fraction(100001, 100)


def test_out_of_year_salary_election_does_not_block_current_projection():
    employment = calculate(salary=[period("salary", "80000")])
    future = replace(sacrifice("future", "salary", percent="2", election="2027-04-05",
                               effective="2027-04-06"), qualifies=None)
    result = pension(employment, [future])
    assert result.taxable_salary_gbp == 80000
    assert result.employment_lines[0].reductions == ()
    assert result.payroll_sources == (future,)


@pytest.mark.parametrize(("base", "eligible", "amount", "expected"), [
    (None, None, "10", "incomplete"),
    ("stated_amount", "50", "50.01", "input_error"),
    ("stated_amount", "1000.01", "10", "input_error"),
])
def test_payroll_reduction_requires_a_known_eligible_base_and_respects_its_cap(base, eligible, amount, expected):
    employment = calculate(salary=[period("salary", "0")], bonuses=[pay("bonus", "1000")])
    item = replace(sacrifice("sacrifice", "bonus", amount=amount),
                   base=base, eligible_gbp=None if eligible is None else Decimal(eligible))
    result = pension(employment, [item])
    assert result.status == expected
    assert result.taxable_bonus_gbp is None


def test_empty_pensions_and_gift_aid_require_coverage_confirmation():
    result = pension(calculate(salary=[period("salary", "80000")]), confirmed=False)
    assert result.status == "incomplete"
    assert result.net_income_deduction_gbp is None
