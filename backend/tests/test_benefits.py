from decimal import Decimal
from fractions import Fraction

import pytest

from test_employment import calculate, dates, pay, payroll, period
from vestor_domain import benefits as domain
from vestor_domain.employment import PayrollComponent
from vestor_domain.tax_year import TaxRules, select_tax_rules


RULES = select_tax_rules(2026, "england", standard_treatment=True)
assert isinstance(RULES, TaxRules)


def benefit(key="annual", start="2026-04-06", end="2027-04-05", **changes):
    fields = dict(
        period_id=key, benefit_id="medical", category="family medical",
        dates=dates(start, end), taxability="yes", source_status="forecast",
        source_note="Synthetic benefit evidence", basis="annual_taxable",
        taxable_gbp=Decimal("2400"), daily_apportionment_confirmed=True,
        included_in_payroll=False,
    )
    return domain.BenefitPeriod(**(fields | changes))


def resolve(*records, employment=None, confirmed=True):
    return domain.calculate_benefits(
        RULES, benefits=records,
        employment=employment if employment is not None else calculate(salary=[period("salary", "80000")]),
        coverage_confirmed=confirmed,
    )


def test_renewal_f3_uses_inclusive_clipped_dates_and_exact_amounts():
    result = resolve(
        benefit("old", "2026-03-01", "2026-10-31"),
        benefit("new", "2026-11-01", "2027-10-31", taxable_gbp=Decimal("3000")),
    )
    assert result.status == "estimated"
    assert result.taxable_gbp == Fraction(969600, 365)
    assert [line.period_fraction for line in result.lines] == [Fraction(209, 365), Fraction(156, 365)]
    assert result.rule_version == RULES.version
    assert result.lines[0].covered == dates("2026-04-06", "2026-10-31")


@pytest.mark.parametrize(("changes", "status", "expected"), [
    ({"taxability": "unknown"}, "incomplete", None),
    ({"taxable_gbp": None}, "incomplete", None),
    ({"daily_apportionment_confirmed": False}, "incomplete", None),
    ({"taxability": "no", "taxable_gbp": None}, "estimated", 0),
    ({"included_in_payroll": None}, "incomplete", None),
    ({"employee_contribution_gbp": Decimal("120"), "taxable_gbp": Decimal("1200")}, "estimated", 1200),
])
def test_taxability_and_employee_contribution_are_explicit_evidence(changes, status, expected):
    record = benefit(annual_premium_gbp=Decimal("3500"), **changes)
    result = resolve(record)
    assert result.status == status
    assert result.taxable_gbp == expected
    assert result.lines[0].source == record
    if record.taxability == "no":
        assert result.lines[0].disposition == "excluded"
        assert result.lines[0].explanation


def test_absence_requires_confirmation():
    assert resolve().taxable_gbp == 0
    assert resolve(confirmed=False).status == "incomplete"
    assert resolve(confirmed=False).taxable_gbp is None


def test_same_benefit_renewals_cannot_overlap_even_on_one_day():
    result = resolve(
        benefit("old", end="2026-11-01"),
        benefit("new", start="2026-11-01"),
    )
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_distinct_benefits_can_overlap():
    result = resolve(benefit("one"), benefit("two", benefit_id="travel", category="travel"))
    assert result.taxable_gbp == 4800


def actual(key="actual", start="2026-11-01", end="2026-11-30", **changes):
    fields = dict(
        source_status="actual", basis="p11d", taxable_gbp=Decimal("350"),
        daily_apportionment_confirmed=False, replaces_forecast_ids=("annual",),
    )
    return benefit(key, start, end, **(fields | changes))


def test_partial_actual_replaces_only_explicit_covered_days():
    result = resolve(benefit(), actual())
    assert result.status == "estimated"
    assert result.taxable_gbp == Fraction(804000, 365) + 350
    replaced, = [line for line in result.lines if line.disposition == "replaced"]
    assert replaced.covered == dates("2026-11-01", "2026-11-30")
    assert replaced.replaced_by == "actual"


@pytest.mark.parametrize(("start", "end", "status", "value"), [
    ("2026-04-06", "2027-04-05", "confirmed", 350),
    ("2027-04-06", "2027-04-06", "confirmed", 0),
    ("2027-04-05", "2027-04-06", "incomplete", None),
])
def test_actual_value_is_never_prorated_across_tax_years(start, end, status, value):
    result = resolve(actual(start=start, end=end, replaces_forecast_ids=()))
    assert result.status == status
    assert result.taxable_gbp == value


def test_unconfirmed_actual_does_not_remove_forecast_evidence():
    result = resolve(benefit(), actual(taxable_gbp=None))
    assert result.status == "incomplete"
    assert result.taxable_gbp is None
    assert result.lines[0].amount_gbp == 2400


@pytest.mark.parametrize(("changes", "components", "expected"), [
    ({}, (PayrollComponent("actual", "benefit", Decimal("350")),), "confirmed"),
    ({"included_in_payroll": False, "payroll_ids": ()},
     (PayrollComponent("actual", "benefit", Decimal("350")),), "incomplete"),
    ({}, (PayrollComponent("actual", "benefit", Decimal("300")),), "incomplete"),
    ({}, (), "incomplete"),
    ({}, None, "incomplete"),
    ({}, (PayrollComponent("other", "benefit", Decimal("350")),), "incomplete"),
])
def test_actual_payroll_reconciles_both_directions(changes, components, expected):
    employment = calculate(payroll=[payroll(
        pay("payroll", "80350"), "2026-04-06", "2027-04-05", components=components,
    )])
    record = actual(start="2026-04-06", end="2027-04-05", **(
        {"basis": "payrolled", "included_in_payroll": True, "payroll_ids": ("payroll",)} | changes
    ))
    result = resolve(benefit(), record, employment=employment)
    assert result.status == expected
    if expected == "confirmed":
        assert employment.gross_salary_gbp == 80000
        assert result.included_in_payroll_gbp == 350
        assert result.taxable_gbp == 350
        assert employment.gross_salary_gbp + result.taxable_gbp == 80350
    else:
        assert result.taxable_gbp is None
        assert result.warnings


def test_replaced_payroll_components_do_not_count():
    employment = calculate(payroll=[
        payroll(
            pay("estimated-pay", "82400", source="forecast"), "2026-04-06", "2027-04-05",
            components=(PayrollComponent("annual", "benefit", Decimal("2400")),),
        ),
        payroll(
            pay("actual-pay", "80350", replaces="estimated-pay"), "2026-04-06", "2027-04-05",
            components=(PayrollComponent("actual", "benefit", Decimal("350")),),
        ),
    ])
    result = resolve(benefit(), actual(
        start="2026-04-06", end="2027-04-05",
        basis="payrolled", included_in_payroll=True, payroll_ids=("actual-pay",),
    ), employment=employment)
    assert result.status == "confirmed"
    assert result.taxable_gbp == 350


def test_in_year_benefit_conflicts_with_component_in_outside_year_payroll():
    employment = calculate(payroll=[payroll(
        pay("outside-payroll", "80350", on="2027-04-06"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("actual", "benefit", Decimal("350")),),
    )])
    result = resolve(actual(replaces_forecast_ids=()), employment=employment)
    assert result.status == "incomplete"
    assert result.taxable_gbp is None
    assert any(warning.field == "actual" for warning in result.warnings)


def test_actual_can_replace_multiple_explicit_renewal_periods():
    result = resolve(
        benefit("old", end="2026-10-31"),
        benefit("new", start="2026-11-01", taxable_gbp=Decimal("3000")),
        actual(start="2026-04-06", end="2027-04-05", replaces_forecast_ids=("old", "new")),
    )
    assert result.status == "confirmed"
    assert result.taxable_gbp == 350
    assert [line.replaced_by for line in result.lines if line.disposition == "replaced"] == ["actual", "actual"]


def test_payrolled_amount_can_reconcile_against_multiple_named_payments():
    employment = calculate(payroll=[
        payroll(
            pay("first", "45150", on="2026-11-01"), "2026-04-06", "2026-11-01",
            components=(PayrollComponent("actual", "benefit", Decimal("150")),),
        ),
        payroll(
            pay("second", "35200"), "2026-11-02", "2027-04-05",
            components=(PayrollComponent("actual", "benefit", Decimal("200")),),
        ),
    ])
    result = resolve(actual(
        start="2026-04-06", end="2027-04-05", replaces_forecast_ids=(),
        basis="payrolled", included_in_payroll=True, payroll_ids=("first", "second"),
    ), employment=employment)
    assert result.status == "confirmed"
    assert result.included_in_payroll_gbp == 350
    assert employment.gross_salary_gbp == 80000


@pytest.mark.parametrize("changes", [
    {"replaces_forecast_ids": ("missing",)},
    {"benefit_id": "different-benefit"},
    {"source_status": "forecast"},
])
def test_replacement_must_identify_supplied_same_benefit_forecast(changes):
    result = resolve(benefit(), actual(**changes))
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_overlapping_actual_overrides_are_rejected():
    result = resolve(benefit(), actual(), actual("other"))
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_nonoverlapping_actuals_replace_distinct_forecast_days():
    result = resolve(
        benefit(), actual("first"), actual("second", start="2026-12-01", end="2026-12-31"),
    )
    assert result.status == "estimated"
    # 304 remaining forecast days plus two actual amounts of 350.
    assert result.taxable_gbp == Fraction(729600, 365) + 700


@pytest.mark.parametrize("changes", [
    {"taxable_gbp": 2400.0},
    {"annual_premium_gbp": Decimal("-1")},
    {"employee_contribution_gbp": Decimal("1.001")},
    {"included_in_payroll": "false"},
    {"daily_apportionment_confirmed": "true"},
    {"taxability": "exempt"},
    {"basis": "premium"},
    {"payroll_ids": ("pay", "pay")},
])
def test_invalid_benefit_evidence_raises_field_errors(changes):
    from vestor_domain.primitives import InputError

    with pytest.raises(InputError):
        benefit(**changes)


def test_duplicate_period_ids_are_rejected_even_across_benefits():
    result = resolve(benefit(), benefit(benefit_id="travel"))
    assert result.status == "input_error"
    assert result.taxable_gbp is None
